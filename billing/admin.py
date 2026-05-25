from django.contrib import admin

from .models import CustomerProfile, Package, Purchase


@admin.register(Package)
class PackageAdmin(admin.ModelAdmin):
    list_display = ("name", "speed", "duration_hours", "price", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "description")


@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = ("phone", "package", "amount", "status", "access_code", "created_at", "expires_at")
    list_filter = ("status", "package")
    search_fields = ("phone", "access_code", "checkout_request_id", "mpesa_receipt")
    readonly_fields = ("created_at", "paid_at", "expires_at")


@admin.register(CustomerProfile)
class CustomerProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "phone")
    search_fields = ("user__username", "user__email", "phone")

# Register your models here.
