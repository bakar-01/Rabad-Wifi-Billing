import base64
import datetime as dt
import json
import logging
import os
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)


class MpesaClientError(Exception):
    """Raised when Daraja returns an unusable response."""


def env_value(key: str, default: str = "") -> str:
    value = os.environ.get(key, default)
    return value.strip().strip('"').strip("'")


def configured() -> bool:
    keys = ["MPESA_CONSUMER_KEY", "MPESA_CONSUMER_SECRET", "MPESA_SHORTCODE", "MPESA_PASSKEY"]
    return all(env_value(key) for key in keys)


def simulate_payments() -> bool:
    return env_value("MPESA_SIMULATE_PAYMENTS", "false").lower() in {"1", "true", "yes", "on"}


def base_url() -> str:
    return "https://api.safaricom.co.ke" if env_value("MPESA_ENV") == "production" else "https://sandbox.safaricom.co.ke"


def daraja_error_message(exc: urllib.error.HTTPError) -> str:
    body = exc.read().decode("utf-8", errors="replace")
    if not body:
        return f"HTTP Error {exc.code}: {exc.reason}"

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return f"HTTP Error {exc.code}: {body}"

    message = (
        data.get("errorMessage")
        or data.get("fault", {}).get("faultstring")
        or data.get("ResultDesc")
        or data.get("message")
        or body
    )
    return f"HTTP Error {exc.code}: {message}"


def url_error_message(exc: urllib.error.URLError) -> str:
    reason = getattr(exc, "reason", exc)
    return str(reason)


def response_json(response) -> dict:
    body = response.read().decode("utf-8", errors="replace")
    try:
        data = json.loads(body or "{}")
    except json.JSONDecodeError as exc:
        raise MpesaClientError("M-Pesa returned an invalid JSON response.") from exc

    if not isinstance(data, dict):
        raise MpesaClientError("M-Pesa returned an unexpected response.")
    return data


def stk_configuration_error() -> str:
    env = env_value("MPESA_ENV", "sandbox")
    shortcode = env_value("MPESA_SHORTCODE")
    passkey = env_value("MPESA_PASSKEY")
    callback_url = env_value("MPESA_CALLBACK_URL")

    if env == "sandbox" and shortcode == "174379" and len(passkey) < 100:
        return (
            "Wrong M-Pesa STK passkey for sandbox shortcode 174379. "
            "OAuth works, but STK Push needs the Lipa Na M-Pesa Online passkey from the Daraja app, "
            "not the consumer secret or initiator password."
        )
    if not callback_url.startswith("https://"):
        return "MPESA_CALLBACK_URL must be a public HTTPS URL for STK Push callbacks."
    return ""


def token() -> str:
    credentials = f"{env_value('MPESA_CONSUMER_KEY')}:{env_value('MPESA_CONSUMER_SECRET')}"
    encoded = base64.b64encode(credentials.encode()).decode()
    request = urllib.request.Request(
        f"{base_url()}/oauth/v1/generate?grant_type=client_credentials",
        headers={"Authorization": f"Basic {encoded}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = response_json(response)
    except urllib.error.HTTPError as exc:
        raise MpesaClientError(daraja_error_message(exc)) from exc
    except urllib.error.URLError as exc:
        raise MpesaClientError(f"Network error: {url_error_message(exc)}") from exc

    access_token = data.get("access_token")
    if not access_token:
        raise MpesaClientError("OAuth response did not include an access token.")
    return access_token


def initiate_stk_push(phone: str, amount: int, purchase_id: int) -> dict:
    if simulate_payments() or not configured():
        reason = "simulation mode is enabled" if simulate_payments() else "M-Pesa credentials are not configured"
        return {
            "ok": True,
            "simulated": True,
            "checkout_request_id": f"SIM-{purchase_id}",
            "merchant_request_id": f"SIM-MERCHANT-{purchase_id}",
            "message": f"Payment simulated because {reason}.",
        }

    config_error = stk_configuration_error()
    if config_error:
        return {"ok": False, "message": f"M-Pesa request failed: {config_error}"}

    try:
        access_token = token()
    except MpesaClientError as exc:
        logger.warning("M-Pesa OAuth failed for purchase %s: %s", purchase_id, exc)
        return {"ok": False, "message": f"M-Pesa request failed: {exc}"}

    timestamp = dt.datetime.now().strftime("%Y%m%d%H%M%S")
    shortcode = env_value("MPESA_SHORTCODE")
    password = base64.b64encode(f"{shortcode}{env_value('MPESA_PASSKEY')}{timestamp}".encode()).decode()
    payload = {
        "BusinessShortCode": shortcode,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": env_value("MPESA_TRANSACTION_TYPE", "CustomerPayBillOnline"),
        "Amount": amount,
        "PartyA": phone,
        "PartyB": shortcode,
        "PhoneNumber": phone,
        "CallBackURL": env_value("MPESA_CALLBACK_URL", "https://example.com/mpesa/callback/"),
        "AccountReference": f"WIFI-{purchase_id}",
        "TransactionDesc": "WiFi package purchase",
    }
    request = urllib.request.Request(
        f"{base_url()}/mpesa/stkpush/v1/processrequest",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            data = response_json(response)
    except urllib.error.HTTPError as exc:
        return {"ok": False, "message": f"M-Pesa request failed: {daraja_error_message(exc)}"}
    except urllib.error.URLError as exc:
        return {"ok": False, "message": f"M-Pesa request failed: {url_error_message(exc)}"}
    except MpesaClientError as exc:
        return {"ok": False, "message": f"M-Pesa request failed: {exc}"}

    return {
        "ok": str(data.get("ResponseCode")) == "0",
        "checkout_request_id": data.get("CheckoutRequestID", ""),
        "merchant_request_id": data.get("MerchantRequestID", ""),
        "message": data.get("CustomerMessage") or data.get("errorMessage") or "M-Pesa request sent.",
    }
