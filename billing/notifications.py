import logging
import os

from django.utils import timezone

from .models import Subscription

logger = logging.getLogger(__name__)


def subscription_sms(subscription: Subscription) -> str:
    expires = timezone.localtime(subscription.expires_at).strftime("%d %B %Y %H:%M")
    return (
        "Payment Received\n"
        f"Package: {subscription.package.name}\n"
        f"Amount: KSh {subscription.package.price}\n"
        f"Username: {subscription.username}\n"
        f"Password: {subscription.password}\n"
        f"Expires: {expires}\n"
        "Keep this SMS to reconnect later."
    )


def send_subscription_sms(subscription: Subscription) -> bool:
    username = os.environ.get("AFRICASTALKING_USERNAME")
    api_key = os.environ.get("AFRICASTALKING_API_KEY")
    sender_id = os.environ.get("AFRICASTALKING_SENDER_ID")
    if not username or not api_key:
        logger.info("SMS skipped because Africa's Talking credentials are not configured.")
        return False

    try:
        import africastalking

        africastalking.initialize(username, api_key)
        sms = africastalking.SMS
        kwargs = {"message": subscription_sms(subscription), "recipients": [f"+{subscription.phone_number}"]}
        if sender_id:
            kwargs["sender_id"] = sender_id
        sms.send(**kwargs)
        return True
    except Exception as exc:
        logger.warning("SMS notification failed for subscription %s: %s", subscription.pk, exc)
        return False
