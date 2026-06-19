import json
import os
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from .models import MpesaTransaction, Package, Purchase, Subscription
from .mpesa import initiate_stk_push
from .notifications import subscription_sms
from .services import deactivate_expired_subscriptions


class BillingFlowTests(TestCase):
    def setUp(self):
        self.package = Package.objects.create(
            name="Test Day",
            speed="5 Mbps",
            profile="5Mbps",
            duration_hours=24,
            price=100,
            description="Test package",
        )

    def test_mpesa_simulation_flag_skips_daraja(self):
        with patch.dict(os.environ, {"MPESA_SIMULATE_PAYMENTS": "true"}):
            result = initiate_stk_push("254712345678", 20, 99)

        self.assertTrue(result["ok"])
        self.assertTrue(result["simulated"])
        self.assertEqual(result["checkout_request_id"], "SIM-99")

    def test_register_rejects_duplicate_email_case_insensitive(self):
        User = get_user_model()
        User.objects.create_user(username="customer@example.com", email="customer@example.com", password="StrongPass123")

        response = self.client.post(
            reverse("register"),
            {
                "first_name": "Customer",
                "email": "Customer@Example.com",
                "phone": "0712345678",
                "password1": "StrongPass123",
                "password2": "StrongPass123",
            },
        )

        self.assertContains(response, "That email is already registered.")
        self.assertEqual(User.objects.filter(email__iexact="customer@example.com").count(), 1)

    def test_user_email_unique_at_database_level(self):
        User = get_user_model()
        User.objects.create_user(username="first@example.com", email="first@example.com", password="StrongPass123")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                User.objects.create_user(
                    username="second@example.com",
                    email="FIRST@example.com",
                    password="StrongPass123",
                )

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="WaveNet Billing <no-reply@example.com>",
    )
    def test_password_reset_sends_email_to_registered_address(self):
        User = get_user_model()
        User.objects.create_user(username="reset@example.com", email="reset@example.com", password="StrongPass123")

        response = self.client.post(reverse("password_reset"), {"email": "RESET@example.com"})

        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Reset your WaveNet Billing password", mail.outbox[0].subject)
        self.assertIn("/reset/", mail.outbox[0].body)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_password_reset_does_not_email_unknown_address(self):
        response = self.client.post(reverse("password_reset"), {"email": "missing@example.com"})

        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)

    @patch("billing.services.create_hotspot_user")
    @patch("billing.views.initiate_stk_push")
    def test_simulated_purchase_creates_transaction_subscription_and_router_user(self, stk_push, hotspot_user):
        stk_push.return_value = {
            "ok": True,
            "simulated": True,
            "checkout_request_id": "SIM-1",
            "merchant_request_id": "SIM-MERCHANT-1",
            "message": "Simulated",
        }
        hotspot_user.return_value = {"success": True, "user_id": "router-id"}

        response = self.client.post(
            reverse("buy"),
            {"package": self.package.pk, "phone": "0712345678"},
        )

        self.assertEqual(response.status_code, 302)
        purchase = Purchase.objects.get()
        transaction = MpesaTransaction.objects.get(purchase=purchase)
        subscription = Subscription.objects.get(purchase=purchase)
        self.assertEqual(purchase.status, Purchase.STATUS_ACTIVE)
        self.assertEqual(transaction.status, MpesaTransaction.STATUS_SUCCESS)
        self.assertEqual(subscription.username, "254712345678")
        self.assertEqual(subscription.password, purchase.access_code)
        hotspot_user.assert_called_once_with(username="254712345678", password=purchase.access_code, profile="5Mbps")

    def test_subscription_sms_contains_guest_reconnect_credentials(self):
        purchase = Purchase.objects.create(
            package=self.package,
            phone="254712345678",
            amount=self.package.price,
            access_code="WF-SMS123",
            status=Purchase.STATUS_ACTIVE,
            expires_at=timezone.now() + timezone.timedelta(hours=1),
        )
        subscription = Subscription.objects.create(
            purchase=purchase,
            phone_number=purchase.phone,
            package=self.package,
            username=purchase.phone,
            password=purchase.access_code,
            expires_at=purchase.expires_at,
        )

        message = subscription_sms(subscription)

        self.assertIn("Username: 254712345678", message)
        self.assertIn("Password: WF-SMS123", message)
        self.assertIn("Keep this SMS to reconnect later.", message)

    def test_guest_receipt_requires_access_token(self):
        purchase = Purchase.objects.create(
            package=self.package,
            phone="254712345678",
            amount=self.package.price,
            access_code="WF-LOCK1",
            status=Purchase.STATUS_ACTIVE,
            expires_at=timezone.now() + timezone.timedelta(hours=1),
        )

        blocked_response = self.client.get(reverse("receipt", args=[purchase.id]))
        allowed_response = self.client.get(f"{reverse('receipt', args=[purchase.id])}?token=WF-LOCK1")

        self.assertEqual(blocked_response.status_code, 403)
        self.assertContains(allowed_response, "WF-LOCK1")

    def test_purchase_redirects_to_tokenized_receipt(self):
        with patch("billing.views.initiate_stk_push") as stk_push:
            stk_push.return_value = {
                "ok": True,
                "simulated": False,
                "checkout_request_id": "STK-1",
                "merchant_request_id": "MERCHANT-1",
                "message": "Sent",
            }

            response = self.client.post(reverse("buy"), {"package": self.package.pk, "phone": "0712345678"})

        purchase = Purchase.objects.get()
        self.assertEqual(response.status_code, 302)
        self.assertIn(f"/receipt/{purchase.id}/?token={purchase.access_code}", response["Location"])

    @patch("billing.services.create_hotspot_user")
    def test_mpesa_callback_activates_pending_purchase(self, hotspot_user):
        hotspot_user.return_value = {"success": True, "user_id": "router-id"}
        purchase = Purchase.objects.create(
            package=self.package,
            phone="254712345678",
            amount=self.package.price,
            access_code="WF-123456",
            checkout_request_id="ws_CO_123",
        )
        MpesaTransaction.objects.create(
            purchase=purchase,
            phone_number=purchase.phone,
            amount=purchase.amount,
            checkout_request_id=purchase.checkout_request_id,
        )
        payload = {
            "Body": {
                "stkCallback": {
                    "MerchantRequestID": "merchant-1",
                    "CheckoutRequestID": "ws_CO_123",
                    "ResultCode": 0,
                    "ResultDesc": "Success",
                    "CallbackMetadata": {
                        "Item": [
                            {"Name": "Amount", "Value": 100},
                            {"Name": "MpesaReceiptNumber", "Value": "RCP123"},
                            {"Name": "PhoneNumber", "Value": 254712345678},
                        ]
                    },
                }
            }
        }

        response = self.client.post(
            reverse("mpesa_callback"),
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        purchase.refresh_from_db()
        transaction = purchase.transaction
        self.assertEqual(purchase.status, Purchase.STATUS_ACTIVE)
        self.assertEqual(purchase.mpesa_receipt, "RCP123")
        self.assertEqual(transaction.status, MpesaTransaction.STATUS_SUCCESS)
        self.assertTrue(Subscription.objects.filter(purchase=purchase, active=True).exists())

    @patch("billing.services.remove_hotspot_user")
    def test_deactivate_expired_subscriptions_removes_router_user(self, remove_hotspot_user):
        purchase = Purchase.objects.create(
            package=self.package,
            phone="254712345678",
            amount=self.package.price,
            access_code="WF-654321",
            status=Purchase.STATUS_ACTIVE,
        )
        subscription = Subscription.objects.create(
            purchase=purchase,
            phone_number=purchase.phone,
            package=self.package,
            username=purchase.phone,
            password=purchase.access_code,
            expires_at=timezone.now() - timezone.timedelta(minutes=1),
        )

        count = deactivate_expired_subscriptions()

        self.assertEqual(count, 1)
        subscription.refresh_from_db()
        self.assertFalse(subscription.active)
        remove_hotspot_user.assert_called_once_with("254712345678")

    @patch("billing.views.sync_subscription_router_user")
    def test_reconnect_finds_active_subscription_by_password(self, sync_router):
        purchase = Purchase.objects.create(
            package=self.package,
            phone="254712345678",
            amount=self.package.price,
            access_code="WF-ABC123",
            status=Purchase.STATUS_ACTIVE,
            expires_at=timezone.now() + timezone.timedelta(hours=1),
        )
        subscription = Subscription.objects.create(
            purchase=purchase,
            phone_number=purchase.phone,
            package=self.package,
            username=purchase.phone,
            password=purchase.access_code,
            expires_at=purchase.expires_at,
            router_user_created=True,
        )
        sync_router.return_value = subscription

        response = self.client.post(reverse("reconnect"), {"code": "wf-abc123"})

        self.assertContains(response, "254712345678")
        self.assertContains(response, "WF-ABC123")
        self.assertContains(response, 'id="hotspot-login"')
        self.assertContains(response, "Connect now")
        sync_router.assert_called_once_with(subscription)

    @patch("billing.views.sync_subscription_router_user")
    def test_reconnect_finds_active_subscription_by_mpesa_receipt(self, sync_router):
        purchase = Purchase.objects.create(
            package=self.package,
            phone="254712345678",
            amount=self.package.price,
            access_code="WF-ABC123",
            mpesa_receipt="RCP123",
            status=Purchase.STATUS_ACTIVE,
            expires_at=timezone.now() + timezone.timedelta(hours=1),
        )
        subscription = Subscription.objects.create(
            purchase=purchase,
            phone_number=purchase.phone,
            package=self.package,
            username=purchase.phone,
            password=purchase.access_code,
            expires_at=purchase.expires_at,
            router_user_created=True,
        )
        sync_router.return_value = subscription

        response = self.client.post(reverse("reconnect"), {"code": "rcp123"})

        self.assertContains(response, "WF-ABC123")
        self.assertContains(response, 'id="hotspot-login"')
        sync_router.assert_called_once_with(subscription)

    def test_reconnect_rejects_expired_subscription(self):
        purchase = Purchase.objects.create(
            package=self.package,
            phone="254712345678",
            amount=self.package.price,
            access_code="WF-OLD123",
            status=Purchase.STATUS_ACTIVE,
            expires_at=timezone.now() - timezone.timedelta(minutes=1),
        )
        Subscription.objects.create(
            purchase=purchase,
            phone_number=purchase.phone,
            package=self.package,
            username=purchase.phone,
            password=purchase.access_code,
            expires_at=purchase.expires_at,
        )

        response = self.client.post(reverse("reconnect"), {"code": "WF-OLD123"})

        self.assertContains(response, "This package has expired")
        self.assertNotContains(response, "Expires")

    def test_reconnect_warns_for_wrong_code(self):
        response = self.client.post(reverse("reconnect"), {"code": "WRONG-CODE"})

        self.assertContains(response, "incorrect")
        self.assertNotContains(response, "Connect now")

    @patch("billing.views.sync_subscription_router_user")
    def test_reconnect_active_subscription_waits_when_router_not_ready(self, sync_router):
        purchase = Purchase.objects.create(
            package=self.package,
            phone="254712345678",
            amount=self.package.price,
            access_code="WF-WAIT1",
            status=Purchase.STATUS_ACTIVE,
            expires_at=timezone.now() + timezone.timedelta(hours=1),
        )
        subscription = Subscription.objects.create(
            purchase=purchase,
            phone_number=purchase.phone,
            package=self.package,
            username=purchase.phone,
            password=purchase.access_code,
            expires_at=purchase.expires_at,
            router_user_created=False,
        )
        sync_router.return_value = subscription

        response = self.client.post(reverse("reconnect"), {"code": "WF-WAIT1"})

        self.assertContains(response, "router is not ready")
        self.assertNotContains(response, 'id="hotspot-login"')
