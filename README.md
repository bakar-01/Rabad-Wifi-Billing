# WaveNet WiFi Billing

A Django hotspot billing system for M-Pesa STK Push payments and MikroTik Hotspot provisioning.

## Features

- Captive-portal style package purchase page
- Guest checkout by Safaricom phone number
- M-Pesa transaction records and callback processing
- Subscription creation with username/password vouchers
- MikroTik hotspot user creation and expiry removal
- Optional customer accounts and dashboards with one account per email address
- Email password reset links for account recovery
- SMS vouchers with WiFi username/password for guest reconnection
- Protected receipt pages so WiFi credentials are not exposed by sequential IDs
- Operator dashboard for revenue, payments, active users, and transactions
- Optional SMS notification through Africa's Talking
- Celery task for automatic expired-user cleanup

## Run locally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Seeded admin:

- Email: `admin@wifi.local`
- Password: `admin123`

## Main URLs

- `/` package purchase page
- `/register/` customer account creation
- `/login/` sign in
- `/dashboard/` customer purchase history
- `/operator/` operator dashboard
- `/admin/` Django admin
- `/mpesa/callback/` Safaricom callback URL

## Configuration

Copy `.env.example` to `.env`, then set the values for your environment.

```powershell
Copy-Item .env.example .env
```

For production, set a unique `DJANGO_SECRET_KEY`, set `DJANGO_DEBUG=false`, fill `DJANGO_ALLOWED_HOSTS`, and configure SMTP values so password reset emails can be delivered. Enable HTTPS security settings such as `DJANGO_SECURE_SSL_REDIRECT=true` after TLS is correctly configured on your domain or proxy.

When M-Pesa credentials are not configured, purchases are simulated so the app can be developed offline.

To enable MikroTik provisioning, set:

```env
MIKROTIK_ENABLED=true
MIKROTIK_HOST=192.168.88.1
MIKROTIK_USERNAME=admin
MIKROTIK_PASSWORD=your-router-password
```

## Expiry worker

Run Redis, then start Celery:

```powershell
celery -A wifibilling worker -l info
```

Schedule `billing.tasks.deactivate_expired_users` with Celery Beat, django-celery-beat, Windows Task Scheduler, or any cron-style scheduler.
