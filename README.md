# WaveNet WiFi Billing

A Django WiFi billing system with:

- Guest package purchase by phone number
- Optional customer accounts and dashboard
- Django admin plus an operator dashboard for purchases, access codes, pending payments, and revenue
- M-Pesa STK Push integration with automatic simulation when credentials are missing
- SQLite storage and responsive templates

## Run

```powershell
python manage.py migrate
python manage.py runserver
```

Open http://127.0.0.1:8000.

Default admin:

- Email: `admin@wifi.local`
- Password: `admin123`

## M-Pesa setup

Set these environment variables before starting the app:

```powershell
$env:MPESA_ENV="sandbox"
$env:MPESA_CONSUMER_KEY="your-consumer-key"
$env:MPESA_CONSUMER_SECRET="your-consumer-secret"
$env:MPESA_SHORTCODE="174379"
$env:MPESA_PASSKEY="your-passkey"
$env:MPESA_CALLBACK_URL="https://your-domain.example/mpesa/callback"
python app.py
```

Without those values, purchases are simulated and activated immediately so you can test the complete flow locally.

## Main URLs

- `/` package purchase page
- `/register/` customer account creation
- `/login/` sign in
- `/dashboard/` customer purchase history
- `/operator/` operator dashboard
- `/admin/` Django admin
