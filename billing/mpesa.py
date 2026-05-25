import base64
import datetime as dt
import json
import os
import urllib.error
import urllib.request


def configured() -> bool:
    keys = ["MPESA_CONSUMER_KEY", "MPESA_CONSUMER_SECRET", "MPESA_SHORTCODE", "MPESA_PASSKEY"]
    return all(os.environ.get(key) for key in keys)


def base_url() -> str:
    return "https://api.safaricom.co.ke" if os.environ.get("MPESA_ENV") == "production" else "https://sandbox.safaricom.co.ke"


def token() -> str:
    credentials = f"{os.environ['MPESA_CONSUMER_KEY']}:{os.environ['MPESA_CONSUMER_SECRET']}"
    encoded = base64.b64encode(credentials.encode()).decode()
    request = urllib.request.Request(
        f"{base_url()}/oauth/v1/generate?grant_type=client_credentials",
        headers={"Authorization": f"Basic {encoded}"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode())["access_token"]


def initiate_stk_push(phone: str, amount: int, purchase_id: int) -> dict:
    if not configured():
        return {
            "ok": True,
            "simulated": True,
            "checkout_request_id": f"SIM-{purchase_id}",
            "message": "Payment simulated because M-Pesa credentials are not configured.",
        }

    timestamp = dt.datetime.now().strftime("%Y%m%d%H%M%S")
    shortcode = os.environ["MPESA_SHORTCODE"]
    password = base64.b64encode(f"{shortcode}{os.environ['MPESA_PASSKEY']}{timestamp}".encode()).decode()
    payload = {
        "BusinessShortCode": shortcode,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": os.environ.get("MPESA_TRANSACTION_TYPE", "CustomerPayBillOnline"),
        "Amount": amount,
        "PartyA": phone,
        "PartyB": shortcode,
        "PhoneNumber": phone,
        "CallBackURL": os.environ.get("MPESA_CALLBACK_URL", "https://example.com/mpesa/callback/"),
        "AccountReference": f"WIFI-{purchase_id}",
        "TransactionDesc": "WiFi package purchase",
    }
    request = urllib.request.Request(
        f"{base_url()}/mpesa/stkpush/v1/processrequest",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Authorization": f"Bearer {token()}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            data = json.loads(response.read().decode())
    except urllib.error.URLError as exc:
        return {"ok": False, "message": f"M-Pesa request failed: {exc}"}

    return {
        "ok": data.get("ResponseCode") == "0",
        "checkout_request_id": data.get("CheckoutRequestID", ""),
        "message": data.get("CustomerMessage") or data.get("errorMessage") or "M-Pesa request sent.",
    }
