import json
import secrets

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.forms import AuthenticationForm
from django.db.models import Count, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .forms import PurchaseForm, ReconnectForm, RegisterForm
from .models import MpesaTransaction, Package, Purchase, Subscription
from .mpesa import initiate_stk_push
from .services import activate_purchase, fail_purchase, record_transaction, sync_subscription_router_user


def access_code() -> str:
    return "WF-" + secrets.token_hex(3).upper()


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
    result = initiate_stk_push(purchase.phone, purchase.amount, purchase.id)
    purchase.checkout_request_id = result.get("checkout_request_id") or f"LOCAL-{purchase.id}"
    purchase.save(update_fields=["checkout_request_id"])
    record_transaction(
        purchase=purchase,
        phone_number=purchase.phone,
        amount=purchase.amount,
        checkout_request_id=purchase.checkout_request_id,
        merchant_request_id=result.get("merchant_request_id", ""),
    )

    if not result.get("ok"):
        fail_purchase(purchase, result.get("message", "M-Pesa request failed."))
        transaction = purchase.transaction
        transaction.status = MpesaTransaction.STATUS_FAILED
        transaction.result_description = result.get("message", "M-Pesa request failed.")
        transaction.save(update_fields=["status", "result_description"])
    elif result.get("simulated"):
        transaction = purchase.transaction
        transaction.status = MpesaTransaction.STATUS_SUCCESS
        transaction.receipt_number = f"SIM{purchase.id:06d}"
        transaction.result_code = 0
        transaction.result_description = "Simulated payment accepted"
        transaction.save(update_fields=["status", "receipt_number", "result_code", "result_description"])
        activate_purchase(purchase, receipt=transaction.receipt_number)
    messages.success(request, result.get("message", "M-Pesa request sent."))
    return redirect("receipt", purchase_id=purchase.id)


def receipt(request, purchase_id):
    purchase = get_object_or_404(Purchase.objects.select_related("package"), id=purchase_id)
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
            subscription = sync_subscription_router_user(matched_subscription)
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
            user = form.save()
            login(request, user)
            return redirect("dashboard")
    else:
        form = RegisterForm()
    return render(request, "register.html", {"form": form})


@csrf_exempt
@require_POST
def mpesa_callback(request):
    try:
        payload = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ResultCode": 1, "ResultDesc": "Invalid JSON"}, status=400)

    stk = payload.get("Body", {}).get("stkCallback", {})
    checkout = stk.get("CheckoutRequestID")
    merchant = stk.get("MerchantRequestID", "")
    result_code = int(stk.get("ResultCode", -1))
    result_description = stk.get("ResultDesc", "")
    metadata = {}
    for item in stk.get("CallbackMetadata", {}).get("Item", []):
        metadata[item.get("Name")] = item.get("Value")

    purchase = Purchase.objects.filter(checkout_request_id=checkout).select_related("package").first()
    transaction = MpesaTransaction.objects.filter(checkout_request_id=checkout).first()
    if transaction:
        transaction.merchant_request_id = merchant or transaction.merchant_request_id
        transaction.result_code = result_code
        transaction.result_description = result_description
        transaction.raw_callback = payload
        transaction.receipt_number = str(metadata.get("MpesaReceiptNumber") or transaction.receipt_number or "")
        transaction.status = MpesaTransaction.STATUS_SUCCESS if result_code == 0 else MpesaTransaction.STATUS_FAILED
        if metadata.get("Amount"):
            transaction.amount = metadata["Amount"]
        if metadata.get("PhoneNumber"):
            transaction.phone_number = str(metadata["PhoneNumber"])
        transaction.save()

    if purchase and result_code == 0:
        receipt = str(metadata.get("MpesaReceiptNumber") or "")
        activate_purchase(purchase, receipt=receipt)
    elif purchase:
        fail_purchase(purchase, result_description)

    return JsonResponse({"ResultCode": 0, "ResultDesc": "Accepted"})

# Create your views here.
