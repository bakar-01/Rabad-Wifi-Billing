from django.conf import settings
from django.db import models
from django.utils import timezone


class Package(models.Model):
    name = models.CharField(max_length=80)
    speed = models.CharField(max_length=40)
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
