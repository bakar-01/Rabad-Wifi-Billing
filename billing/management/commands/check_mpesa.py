from django.core.management.base import BaseCommand

from billing.mpesa import base_url, configured, env_value, initiate_stk_push, simulate_payments, stk_configuration_error, token


class Command(BaseCommand):
    help = "Check Daraja configuration and optionally send a test STK Push."

    def add_arguments(self, parser):
        parser.add_argument("--phone", help="Phone number to receive the test STK Push.")
        parser.add_argument("--amount", type=int, default=1, help="Test amount. Defaults to 1.")

    def handle(self, *args, **options):
        self.stdout.write(f"Environment: {env_value('MPESA_ENV', 'sandbox')}")
        self.stdout.write(f"Base URL: {base_url()}")
        self.stdout.write(f"Shortcode: {env_value('MPESA_SHORTCODE') or '<missing>'}")
        self.stdout.write(f"Callback URL: {env_value('MPESA_CALLBACK_URL') or '<missing>'}")
        self.stdout.write(f"Simulation: {'enabled' if simulate_payments() else 'disabled'}")

        if simulate_payments():
            result = initiate_stk_push(phone=options.get("phone") or "254700000000", amount=options["amount"], purchase_id=0)
            self.stdout.write(self.style.SUCCESS(result.get("message", "Payment simulation enabled.")))
            self.stdout.write(f"CheckoutRequestID: {result.get('checkout_request_id')}")
            return

        if not configured():
            self.stderr.write(self.style.ERROR("Missing one or more M-Pesa credentials."))
            return

        config_error = stk_configuration_error()
        if config_error:
            self.stderr.write(self.style.ERROR(config_error))
            return

        try:
            access_token = token()
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"OAuth token failed: {exc}"))
            return

        self.stdout.write(self.style.SUCCESS(f"OAuth token OK: {access_token[:8]}..."))

        phone = options.get("phone")
        if not phone:
            self.stdout.write("No --phone supplied, skipping STK Push.")
            return

        result = initiate_stk_push(phone=phone, amount=options["amount"], purchase_id=0)
        if result.get("ok"):
            self.stdout.write(self.style.SUCCESS(result.get("message", "STK Push accepted.")))
            self.stdout.write(f"CheckoutRequestID: {result.get('checkout_request_id')}")
        else:
            self.stderr.write(self.style.ERROR(result.get("message", "STK Push failed.")))
