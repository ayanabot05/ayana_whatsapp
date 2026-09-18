"""Phone normalization utility.

All verification is email-only via services/verification.py and routes/account.py.
Email OTP codes are sent through Resend (email_sender.py).
There is no SMS, Twilio, or phone-based OTP in AYANA.
"""
from validation import normalize_phone, validate_phone


def _normalize_phone(phone: str) -> str:
    return normalize_phone(phone)