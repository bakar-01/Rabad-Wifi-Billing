# WaveNet WiFi Billing

A Django WiFi billing system with:

- Guest package purchase by phone number
- Optional customer accounts and dashboard
- Django admin plus an operator dashboard for purchases, access codes, pending payments, and revenue
- M-Pesa STK Push integration with automatic simulation when credentials are missing
- SQLite storage and responsive templates

## Run

```powershell


- Email: `admin@wifi.local`
- Password: `admin123`

## M-Pesa setup

Create a local `.env` file in the project root:

```powershell
Copy-Item .env.example .env
```

Then set your M-Pesa values in `.env`:

```env
MPESA_ENV=sandbox
MPESA_CONSUMER_KEY=your-consumer-key
MPESA_CONSUMER_SECRET=your-consumer-secret
MPESA_SHORTCODE=174379
MPESA_PASSKEY=your-passkey
MPESA_CALLBACK_URL=https://your-domain.example/mpesa/callback/
```



## Main URLs

- `/` package purchase page
- `/register/` customer account creation
- `/login/` sign in
- `/dashboard/` customer purchase history
- `/operator/` operator dashboard
- `/admin/` Django admin
