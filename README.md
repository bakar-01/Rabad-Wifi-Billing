# WaveNet WiFi Billing

A Django hotspot billing system for M-Pesa STK Push payments and MikroTik Hotspot provisioning.

## Features

- Captive-portal style package purchase page
- Guest checkout by Safaricom phone number
- M-Pesa transaction records and callback processing
- Subscription creation with username/password vouchers
- MikroTik hotspot user creation and expiry removal
- Optional customer accounts and dashboards
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

implement security measures for users, a user can only create 0ne account using one email address, add email verification for someone who forgets their password and want to retrieve their account, for a user with no account registered send the wifi connection details to their phone number for purposes of reconnection later, make every securing measure work strictly for the system and everything is right for deployment.
Store user/customer data into the database. 