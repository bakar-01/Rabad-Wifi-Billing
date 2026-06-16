from django.conf import settings
from django.db import models
from django.utils import timezone


class Package(models.Model):
    name = models.CharField(max_length=80)
    speed = models.CharField(max_length=40)
    profile = models.CharField(max_length=50, default="default", help_text="MikroTik hotspot profile name")
    duration_hours = models.PositiveIntegerField()
    price = models.PositiveIntegerField(help_text="Amount in KES")
    description = models.TextField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["price"]

    def __str__(self) -> str:
        return f"{self.name} - KES {self.price}"


class CustomerProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="customer_profile")
    phone = models.CharField(max_length=20)

    def __str__(self) -> str:
        return f"{self.user.get_full_name() or self.user.username} - {self.phone}"


class Purchase(models.Model):
    STATUS_PENDING = "pending"
    STATUS_ACTIVE = "active"
    STATUS_FAILED = "failed"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_FAILED, "Failed"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    package = models.ForeignKey(Package, on_delete=models.PROTECT)
    phone = models.CharField(max_length=20)
    amount = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    checkout_request_id = models.CharField(max_length=120, blank=True)
    mpesa_receipt = models.CharField(max_length=80, blank=True)
    access_code = models.CharField(max_length=20, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.phone} - {self.package.name}"

    def activate(self, receipt: str = "") -> None:
        self.status = self.STATUS_ACTIVE
        self.paid_at = timezone.now()
        self.expires_at = self.paid_at + timezone.timedelta(hours=self.package.duration_hours)
        if receipt:
            self.mpesa_receipt = receipt
        self.save(update_fields=["status", "paid_at", "expires_at", "mpesa_receipt"])


class MpesaTransaction(models.Model):
    STATUS_PENDING = "Pending"
    STATUS_SUCCESS = "Success"
    STATUS_FAILED = "Failed"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_SUCCESS, "Success"),
        (STATUS_FAILED, "Failed"),
    ]

    purchase = models.OneToOneField(Purchase, null=True, blank=True, on_delete=models.SET_NULL, related_name="transaction")
    phone_number = models.CharField(max_length=15)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    receipt_number = models.CharField(max_length=30, null=True, blank=True)
    checkout_request_id = models.CharField(max_length=100, db_index=True)
    merchant_request_id = models.CharField(max_length=100, blank=True)
    result_code = models.IntegerField(null=True, blank=True)
    result_description = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    raw_callback = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.phone_number} - {self.amount} - {self.status}"


class Subscription(models.Model):
    phone_number = models.CharField(max_length=15)
    package = models.ForeignKey(Package, on_delete=models.CASCADE)
    purchase = models.OneToOneField(Purchase, null=True, blank=True, on_delete=models.SET_NULL, related_name="subscription")
    username = models.CharField(max_length=50, db_index=True)
    password = models.CharField(max_length=50)
    activated_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    active = models.BooleanField(default=True)
    router_user_created = models.BooleanField(default=False)
    router_message = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-activated_at"]

    def __str__(self) -> str:
        return f"{self.phone_number} - {self.package.name}"
