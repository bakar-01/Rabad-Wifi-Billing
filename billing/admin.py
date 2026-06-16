from django.contrib import admin

from .models import CustomerProfile, MpesaTransaction, Package, Purchase, Subscription


@admin.register(Package)
class PackageAdmin(admin.ModelAdmin):
    list_display = ("name", "speed", "profile", "duration_hours", "price", "is_active")
    list_filter = ("is_active", "profile")
    search_fields = ("name", "description", "profile")


@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = ("phone", "package", "amount", "status", "access_code", "created_at", "expires_at")
    list_filter = ("status", "package")
    search_fields = ("phone", "access_code", "checkout_request_id", "mpesa_receipt")
    readonly_fields = ("created_at", "paid_at", "expires_at")


@admin.register(MpesaTransaction)
class MpesaTransactionAdmin(admin.ModelAdmin):
    list_display = ("phone_number", "amount", "receipt_number", "checkout_request_id", "status", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("phone_number", "receipt_number", "checkout_request_id", "merchant_request_id")
    readonly_fields = ("created_at", "updated_at", "raw_callback")


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("phone_number", "package", "username", "expires_at", "active", "router_user_created")
    list_filter = ("active", "router_user_created", "package")
    search_fields = ("phone_number", "username", "password")
    readonly_fields = ("activated_at",)


@admin.register(CustomerProfile)
class CustomerProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "phone")
    search_fields = ("user__username", "user__email", "phone")

# Register your models here.
