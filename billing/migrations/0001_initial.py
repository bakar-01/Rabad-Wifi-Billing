# Generated for the WiFi billing demo.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def seed_data(apps, schema_editor):
    Package = apps.get_model("billing", "Package")
    User = apps.get_model("auth", "User")
    packages = [
        ("Quick Browse", "5 Mbps", 3, 20, "Short session for browsing, messaging, and email."),
        ("Day Pass", "10 Mbps", 24, 50, "A reliable day package for streaming and work calls."),
        ("Weekend Max", "15 Mbps", 72, 120, "Three days of faster access for home and visitors."),
        ("Weekly Pro", "20 Mbps", 168, 250, "Best value for steady weekly connectivity."),
    ]
    for name, speed, duration, price, description in packages:
        Package.objects.get_or_create(
            name=name,
            defaults={"speed": speed, "duration_hours": duration, "price": price, "description": description},
        )
    if not User.objects.filter(username="admin@wifi.local").exists():
        from django.contrib.auth.hashers import make_password

        User.objects.create(
            username="admin@wifi.local",
            email="admin@wifi.local",
            first_name="Admin",
            is_staff=True,
            is_superuser=True,
            password=make_password("admin123"),
        )


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Package",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=80)),
                ("speed", models.CharField(max_length=40)),
                ("duration_hours", models.PositiveIntegerField()),
                ("price", models.PositiveIntegerField(help_text="Amount in KES")),
                ("description", models.TextField()),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["price"]},
        ),
        migrations.CreateModel(
            name="CustomerProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("phone", models.CharField(max_length=20)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="customer_profile", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="Purchase",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("phone", models.CharField(max_length=20)),
                ("amount", models.PositiveIntegerField()),
                ("status", models.CharField(choices=[("pending", "Pending"), ("active", "Active"), ("failed", "Failed")], default="pending", max_length=20)),
                ("checkout_request_id", models.CharField(blank=True, max_length=120)),
                ("mpesa_receipt", models.CharField(blank=True, max_length=80)),
                ("access_code", models.CharField(max_length=20, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("paid_at", models.DateTimeField(blank=True, null=True)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("package", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="billing.package")),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.RunPython(seed_data, migrations.RunPython.noop),
    ]
