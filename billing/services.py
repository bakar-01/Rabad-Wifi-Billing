import logging
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from .mikrotik import create_hotspot_user, remove_hotspot_user
from .models import MpesaTransaction, Purchase, Subscription
from .notifications import send_subscription_sms

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ActivationResult:
    purchase: Purchase
    subscription: Subscription | None
    created: bool


def router_message(router_result: dict) -> str:
    return str(router_result.get("error") or router_result.get("user_id") or "")[:255]


def provision_subscription_router_user(subscription: Subscription) -> None:
    try:
        router_result = create_hotspot_user(
            username=subscription.username,
            password=subscription.password,
            profile=subscription.package.profile,
        )
    except Exception as exc:
        logger.exception("Router provisioning failed for subscription %s", subscription.pk)
        router_result = {"success": False, "error": f"Router provisioning failed: {exc}"}

    subscription.router_user_created = bool(router_result.get("success"))
    subscription.router_message = router_message(router_result)
    subscription.save(update_fields=["router_user_created", "router_message"])


def activate_purchase(purchase: Purchase, receipt: str = "") -> ActivationResult:
    """Mark a paid purchase active, create a subscription, and provision MikroTik access."""
    with transaction.atomic():
        purchase = Purchase.objects.select_for_update().select_related("package").get(pk=purchase.pk)
        if purchase.status == Purchase.STATUS_ACTIVE and hasattr(purchase, "subscription"):
            return ActivationResult(purchase=purchase, subscription=purchase.subscription, created=False)

        purchase.activate(receipt=receipt)
        subscription, created = Subscription.objects.get_or_create(
            purchase=purchase,
            defaults={
                "phone_number": purchase.phone,
                "package": purchase.package,
                "username": purchase.phone,
                "password": purchase.access_code,
                "expires_at": purchase.expires_at,
            },
        )

    if created or not subscription.router_user_created:
        provision_subscription_router_user(subscription)

    if created:
        try:
            send_subscription_sms(subscription)
        except Exception:
            logger.exception("SMS notification failed unexpectedly for subscription %s", subscription.pk)

    return ActivationResult(purchase=purchase, subscription=subscription, created=created)


def fail_purchase(purchase: Purchase, description: str = "") -> None:
    purchase.status = Purchase.STATUS_FAILED
    purchase.save(update_fields=["status"])
    if description:
        logger.info("Purchase %s failed: %s", purchase.pk, description)


def record_transaction(
    *,
    purchase: Purchase | None,
    phone_number: str,
    amount,
    checkout_request_id: str,
    merchant_request_id: str = "",
) -> MpesaTransaction:
    transaction_obj, _ = MpesaTransaction.objects.update_or_create(
        checkout_request_id=checkout_request_id,
        defaults={
            "purchase": purchase,
            "phone_number": phone_number,
            "amount": amount,
            "merchant_request_id": merchant_request_id,
        },
    )
    return transaction_obj


def deactivate_expired_subscriptions(now=None) -> int:
    now = now or timezone.now()
    expired = Subscription.objects.filter(active=True, expires_at__lt=now)
    count = 0
    for subscription in expired:
        try:
            removed = remove_hotspot_user(subscription.username)
        except Exception:
            logger.exception("Router cleanup failed for expired subscription %s", subscription.pk)
            removed = False
        if not removed:
            logger.warning("Expired subscription %s was deactivated before router cleanup succeeded.", subscription.pk)
        subscription.active = False
        subscription.save(update_fields=["active"])
        count += 1
    return count


def sync_subscription_router_user(subscription: Subscription) -> Subscription:
    if subscription.router_user_created:
        return subscription

    provision_subscription_router_user(subscription)
    return subscription
