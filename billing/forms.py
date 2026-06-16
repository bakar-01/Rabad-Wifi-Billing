from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from .models import CustomerProfile
from .models import Package


def normalize_phone(phone: str) -> str:
    digits = "".join(ch for ch in phone if ch.isdigit())
    if digits.startswith("0") and len(digits) == 10:
        return "254" + digits[1:]
    if digits.startswith("7") and len(digits) == 9:
        return "254" + digits
    return digits


def valid_phone(phone: str) -> bool:
    normalized = normalize_phone(phone)
    return len(normalized) == 12 and normalized.startswith("254")


class PurchaseForm(forms.Form):
    package = forms.ModelChoiceField(queryset=Package.objects.filter(is_active=True), empty_label=None)
    phone = forms.CharField(max_length=20)

    def clean_phone(self) -> str:
        phone = normalize_phone(self.cleaned_data["phone"])
        if not valid_phone(phone):
            raise forms.ValidationError("Enter a valid Safaricom phone number.")
        return phone


class ReconnectForm(forms.Form):
    code = forms.CharField(
        max_length=80,
        label="M-Pesa code or WiFi password",
        widget=forms.TextInput(attrs={"placeholder": "e.g. SIM000004 or WF-F2A4D8"}),
    )

    def clean_code(self) -> str:
        return self.cleaned_data["code"].strip().upper()


class RegisterForm(UserCreationForm):
    first_name = forms.CharField(max_length=80, label="Name")
    email = forms.EmailField()
    phone = forms.CharField(max_length=20)

    class Meta:
        model = User
        fields = ["first_name", "email", "phone", "password1", "password2"]

    def clean_email(self) -> str:
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(username__iexact=email).exists() or User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("That email is already registered.")
        return email

    def clean_phone(self) -> str:
        phone = normalize_phone(self.cleaned_data["phone"])
        if not valid_phone(phone):
            raise forms.ValidationError("Enter a valid Safaricom phone number.")
        if CustomerProfile.objects.filter(phone=phone).exists():
            raise forms.ValidationError("That phone number is already registered.")
        return phone

    def save(self, commit: bool = True) -> User:
        user = super().save(commit=False)
        user.username = self.cleaned_data["email"]
        user.email = self.cleaned_data["email"]
        user.first_name = self.cleaned_data["first_name"]
        if commit:
            user.save()
            CustomerProfile.objects.create(user=user, phone=self.cleaned_data["phone"])
        return user
