import json
import secrets

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.forms import AuthenticationForm
from django.db.models import Count, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .forms import PurchaseForm, RegisterForm
from .models import Package, Purchase
from .mpesa import initiate_stk_push


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
    purchase.checkout_request_id = result.get("checkout_request_id", "")
    purchase.save(update_fields=["checkout_request_id"])

    if result.get("simulated"):
        purchase.activate(receipt=f"SIM{purchase.id:06d}")
    messages.success(request, result.get("message", "M-Pesa request sent."))
    return redirect("receipt", purchase_id=purchase.id)


def receipt(request, purchase_id):
    purchase = get_object_or_404(Purchase.objects.select_related("package"), id=purchase_id)
    return render(request, "receipt.html", {"purchase": purchase})


@login_required
def dashboard(request):
    purchases = Purchase.objects.select_related("package").filter(user=request.user)
    return render(request, "dashboard.html", {"purchases": purchases})


@user_passes_test(lambda user: user.is_staff)
def operator_dashboard(request):
    purchases = Purchase.objects.select_related("package")[:100]
    metrics = Purchase.objects.aggregate(
        total=Count("id"),
        revenue=Sum("amount", filter=Q(status=Purchase.STATUS_ACTIVE)),
        pending=Count("id", filter=Q(status=Purchase.STATUS_PENDING)),
    )
    return render(request, "operator.html", {"purchases": purchases, "metrics": metrics})


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
    payload = json.loads(request.body.decode() or "{}")
    stk = payload.get("Body", {}).get("stkCallback", {})
    checkout = stk.get("CheckoutRequestID")
    result_code = stk.get("ResultCode")
    receipt = ""
    for item in stk.get("CallbackMetadata", {}).get("Item", []):
        if item.get("Name") == "MpesaReceiptNumber":
            receipt = str(item.get("Value"))
    if checkout and result_code == 0:
        purchase = Purchase.objects.filter(checkout_request_id=checkout).select_related("package").first()
        if purchase:
            purchase.activate(receipt=receipt)
    return JsonResponse({"ResultCode": 0, "ResultDesc": "Accepted"})

# Create your views here.
