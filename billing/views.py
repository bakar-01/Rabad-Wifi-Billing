import json
import logging
import secrets
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .forms import PurchaseForm, ReconnectForm, RegisterForm
from .models import MpesaTransaction, Package, Purchase, Subscription
from .mpesa import initiate_stk_push
from .services import activate_purchase, fail_purchase, record_transaction, sync_subscription_router_user

logger = logging.getLogger(__name__)


def access_code() -> str:
    return "WF-" + secrets.token_hex(3).upper()


def user_can_view_purchase(request, purchase: Purchase) -> bool:
    if request.user.is_authenticated and (request.user.is_staff or purchase.user_id == request.user.id):
        return True

    token = request.GET.get("token", "").strip()
    return bool(token) and secrets.compare_digest(token.upper(), purchase.access_code.upper())


def safe_int(value, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def callback_object(payload: dict, *keys: str) -> dict:
    value = payload
    for key in keys:
        if not isinstance(value, dict):
            return {}
        value = value.get(key, {})
    return value if isinstance(value, dict) else {}


def home(request):
    initial = {}
    if request.user.is_authenticated and hasattr(request.user, "customer_profile"):
        initial["phone"] = request.user.customer_profile.phone
    form = PurchaseForm(initial=initial)
    return render(request, "home.html", {"packages": Package.objects.filter(is_active=True), "form": form})


@require_POST
def buy_package(request):
    form = PurchaseForm(request.POST)
    if not form.is_valid():
        for error in form.errors.values():
            messages.error(request, error[0])
        return redirect("home")

    package = form.cleaned_data["package"]
    purchase = Purchase.objects.create(
        user=request.user if request.user.is_authenticated else None,
        package=package,
        phone=form.cleaned_data["phone"],
        amount=package.price,
        access_code=access_code(),
    )
    try:
        result = initiate_stk_push(purchase.phone, purchase.amount, purchase.id)
    except Exception:
        logger.exception("Unexpected M-Pesa initiation failure for purchase %s", purchase.pk)
        result = {"ok": False, "message": "M-Pesa request failed. Please try again."}

    purchase.checkout_request_id = result.get("checkout_request_id") or f"LOCAL-{purchase.id}"
    purchase.save(update_fields=["checkout_request_id"])
    record_transaction(
        purchase=purchase,
        phone_number=purchase.phone,
        amount=purchase.amount,
        checkout_request_id=purchase.checkout_request_id,
        merchant_request_id=result.get("merchant_request_id", ""),
    )

    activation_failed = False
    if not result.get("ok"):
        fail_purchase(purchase, result.get("message", "M-Pesa request failed."))
        mpesa_transaction = purchase.transaction
        mpesa_transaction.status = MpesaTransaction.STATUS_FAILED
        mpesa_transaction.result_description = result.get("message", "M-Pesa request failed.")
        mpesa_transaction.save(update_fields=["status", "result_description"])
    elif result.get("simulated"):
        mpesa_transaction = purchase.transaction
        mpesa_transaction.status = MpesaTransaction.STATUS_SUCCESS
        mpesa_transaction.receipt_number = f"SIM{purchase.id:06d}"
        mpesa_transaction.result_code = 0
        mpesa_transaction.result_description = "Simulated payment accepted"
        mpesa_transaction.save(update_fields=["status", "receipt_number", "result_code", "result_description"])
        try:
            activate_purchase(purchase, receipt=mpesa_transaction.receipt_number)
        except Exception:
            logger.exception("Simulated purchase activation failed for purchase %s", purchase.pk)
            fail_purchase(purchase, "Activation failed after simulated payment.")
            activation_failed = True
            messages.error(request, "Payment was accepted, but WiFi activation failed. Please contact the operator.")
    if result.get("ok") and not activation_failed:
        messages.success(request, result.get("message", "M-Pesa request sent."))
    elif not activation_failed:
        messages.error(request, result.get("message", "M-Pesa request failed."))
    receipt_url = reverse("receipt", args=[purchase.id])
    return redirect(f"{receipt_url}?{urlencode({'token': purchase.access_code})}")


def receipt(request, purchase_id):
    purchase = get_object_or_404(Purchase.objects.select_related("package"), id=purchase_id)
    if not user_can_view_purchase(request, purchase):
        raise PermissionDenied("You are not allowed to view this receipt.")
    return render(request, "receipt.html", {"purchase": purchase})


def reconnect(request):
    subscription = None
    auto_login = False
    form = ReconnectForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        code = form.cleaned_data["code"]
        now = timezone.now()
        code_filter = (
            Q(password__iexact=code)
            | Q(purchase__access_code__iexact=code)
            | Q(purchase__mpesa_receipt__iexact=code)
            | Q(purchase__transaction__receipt_number__iexact=code)
        )
        matched_subscription = (
            Subscription.objects.select_related("package", "purchase", "purchase__transaction")
            .filter(code_filter)
            .first()
        )
        if matched_subscription and matched_subscription.active and matched_subscription.expires_at > now:
            try:
                subscription = sync_subscription_router_user(matched_subscription)
            except Exception:
                logger.exception("Router sync failed during reconnect for subscription %s", matched_subscription.pk)
                subscription = matched_subscription
            if subscription.router_user_created:
                auto_login = True
                messages.success(request, "Active package found. Reconnecting you to WiFi now.")
            else:
                messages.warning(request, "Your package is active, but the router is not ready yet. Please contact the operator.")
        elif matched_subscription:
            matched_subscription.active = False
            matched_subscription.save(update_fields=["active"])
            messages.error(request, "This package has expired. Please buy a new plan to reconnect.")
        else:
            messages.warning(request, "The M-Pesa code or WiFi password is incorrect. Please check it and try again.")

    return render(
        request,
        "reconnect.html",
        {
            "form": form,
            "subscription": subscription,
            "auto_login": auto_login,
            "mikrotik_login_url": settings.MIKROTIK_LOGIN_URL,
        },
    )


@login_required
def dashboard(request):
    purchases = Purchase.objects.select_related("package").filter(user=request.user)
    return render(request, "dashboard.html", {"purchases": purchases})


@user_passes_test(lambda user: user.is_staff)
def operator_dashboard(request):
    purchases = Purchase.objects.select_related("package")[:100]
    today = timezone.localdate()
    metrics = Purchase.objects.aggregate(
        total=Count("id"),
        revenue=Sum("amount", filter=Q(status=Purchase.STATUS_ACTIVE)),
        pending=Count("id", filter=Q(status=Purchase.STATUS_PENDING)),
        today_revenue=Sum("amount", filter=Q(status=Purchase.STATUS_ACTIVE, paid_at__date=today)),
    )
    active_subscriptions = Subscription.objects.select_related("package").filter(active=True)[:50]
    transactions = MpesaTransaction.objects.select_related("purchase")[:50]
    return render(
        request,
        "operator.html",
        {
            "purchases": purchases,
            "metrics": metrics,
            "active_subscriptions": active_subscriptions,
            "transactions": transactions,
        },
    )


def login_view(request):
    if request.method == "POST":
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            login(request, form.get_user())
            return redirect("dashboard")
    else:
        form = AuthenticationForm()
    return render(request, "login.html", {"form": form})


@require_POST
def logout_view(request):
    logout(request)
    return redirect("home")


def register_view(request):
    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    user = form.save()
            except IntegrityError:
                form.add_error(None, "An account with that email or phone number already exists.")
            else:
                login(request, user)
                return redirect("dashboard")
    else:
        form = RegisterForm()
    return render(request, "register.html", {"form": form})


@csrf_exempt
@require_POST
def mpesa_callback(request):
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"ResultCode": 1, "ResultDesc": "Invalid JSON"}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"ResultCode": 1, "ResultDesc": "Invalid callback payload"}, status=400)

    stk = callback_object(payload, "Body", "stkCallback")
    checkout = stk.get("CheckoutRequestID")
    merchant = stk.get("MerchantRequestID", "")
    result_code = safe_int(stk.get("ResultCode"))
    result_description = stk.get("ResultDesc", "")
    metadata = {}
    callback_metadata = callback_object(stk, "CallbackMetadata")
    items = callback_metadata.get("Item", [])
    if not isinstance(items, list):
        items = []
    for item in items:
        if isinstance(item, dict) and item.get("Name"):
            metadata[item.get("Name")] = item.get("Value")

    if not checkout:
        logger.warning("M-Pesa callback rejected because CheckoutRequestID was missing: %s", payload)
        return JsonResponse({"ResultCode": 1, "ResultDesc": "Missing CheckoutRequestID"}, status=400)

    purchase = Purchase.objects.filter(checkout_request_id=checkout).select_related("package").first()
    mpesa_transaction = MpesaTransaction.objects.filter(checkout_request_id=checkout).first()
    if mpesa_transaction:
        mpesa_transaction.merchant_request_id = merchant or mpesa_transaction.merchant_request_id
        mpesa_transaction.result_code = result_code
        mpesa_transaction.result_description = result_description
        mpesa_transaction.raw_callback = payload
        mpesa_transaction.receipt_number = str(metadata.get("MpesaReceiptNumber") or mpesa_transaction.receipt_number or "")
        mpesa_transaction.status = MpesaTransaction.STATUS_SUCCESS if result_code == 0 else MpesaTransaction.STATUS_FAILED
        if metadata.get("Amount"):
            mpesa_transaction.amount = metadata["Amount"]
        if metadata.get("PhoneNumber"):
            mpesa_transaction.phone_number = str(metadata["PhoneNumber"])
        mpesa_transaction.save()
    else:
        logger.warning("M-Pesa callback received for unknown transaction: %s", checkout)

    if purchase and result_code == 0:
        receipt = str(metadata.get("MpesaReceiptNumber") or "")
        try:
            activate_purchase(purchase, receipt=receipt)
        except Exception:
            logger.exception("Failed to activate purchase %s from M-Pesa callback", purchase.pk)
    elif purchase:
        fail_purchase(purchase, result_description)

    return JsonResponse({"ResultCode": 0, "ResultDesc": "Accepted"})

# Create your views here.
