import json
import os
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import MpesaTransaction, Package, Purchase, Subscription
from .mpesa import initiate_stk_push
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
