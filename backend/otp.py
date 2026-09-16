"""Compatibility import for E.164 normalization.

All verification moved to services/verification.py and routes/account.py.
There is deliberately no Twilio client, SMS path or onscreen OTP mode here.
"""
from validation import validate_phone


def _normalize_phone(phone: str) -> str:
    return validate_phone(phone)