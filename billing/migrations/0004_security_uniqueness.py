from django.db import migrations, models


def create_user_email_index(apps, schema_editor):
    User = apps.get_model("auth", "User")
    seen = set()
    duplicates = set()

    for user in User.objects.exclude(email="").order_by("id"):
        normalized_email = user.email.strip().lower()
        if normalized_email in seen:
            duplicates.add(normalized_email)
        seen.add(normalized_email)
        if user.email != normalized_email:
            user.email = normalized_email
            user.save(update_fields=["email"])

    if duplicates:
        duplicate_list = ", ".join(sorted(duplicates))
        raise RuntimeError(
            "Duplicate user email addresses must be merged before applying this migration: "
            f"{duplicate_list}"
        )

    vendor = schema_editor.connection.vendor
    if vendor == "postgresql":
        schema_editor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS auth_user_email_ci_unique "
            "ON auth_user ((CASE WHEN email = '' THEN NULL ELSE LOWER(email) END))"
        )
    elif vendor == "sqlite":
        schema_editor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS auth_user_email_ci_unique "
            "ON auth_user (CASE WHEN email = '' THEN NULL ELSE LOWER(email) END)"
        )
    elif vendor == "mysql":
        schema_editor.execute(
            "CREATE UNIQUE INDEX auth_user_email_ci_unique "
            "ON auth_user ((CASE WHEN email = '' THEN NULL ELSE LOWER(email) END))"
        )
    else:
        schema_editor.execute("CREATE UNIQUE INDEX auth_user_email_ci_unique ON auth_user (email)")


def drop_user_email_index(apps, schema_editor):
    if schema_editor.connection.vendor == "mysql":
        schema_editor.execute("DROP INDEX auth_user_email_ci_unique ON auth_user")
    else:
        schema_editor.execute("DROP INDEX IF EXISTS auth_user_email_ci_unique")


class Migration(migrations.Migration):
    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("billing", "0003_seed_hotspot_packages"),
    ]

    operations = [
        migrations.AlterField(
            model_name="customerprofile",
            name="phone",
            field=models.CharField(max_length=20, unique=True),
        ),
        migrations.RunPython(create_user_email_index, drop_user_email_index),
    ]
