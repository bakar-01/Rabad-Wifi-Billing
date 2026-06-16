from django.db import migrations


def seed_hotspot_packages(apps, schema_editor):
    Package = apps.get_model("billing", "Package")
    packages = [
        ("1 Hour", "1 Mbps", "1Mbps", 1, 20, "Quick access for browsing and messaging."),
        ("3 Hours", "2 Mbps", "2Mbps", 3, 50, "Short work or study session."),
        ("Full Day", "5 Mbps", "5Mbps", 24, 100, "All-day browsing, calls, and streaming."),
        ("Weekly", "10 Mbps", "10Mbps", 168, 500, "Best value for weekly home or apartment access."),
    ]
    for name, speed, profile, duration, price, description in packages:
        Package.objects.update_or_create(
            name=name,
            defaults={
                "speed": speed,
                "profile": profile,
                "duration_hours": duration,
                "price": price,
                "description": description,
                "is_active": True,
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0002_package_profile_mpesatransaction_subscription"),
    ]

    operations = [
        migrations.RunPython(seed_hotspot_packages, migrations.RunPython.noop),
    ]
