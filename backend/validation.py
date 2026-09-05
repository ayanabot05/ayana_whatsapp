"""Shared input rules: phone length per country code + password strength."""
import re

# dial code -> allowed national-number lengths (digits after the dial code)
PHONE_RULES = {
    "+91": (10,), "+1": (10,), "+44": (10,), "+971": (9,), "+65": (8,), "+61": (9,),
    "+49": (10, 11), "+33": (9,), "+64": (8, 9, 10), "+977": (10,), "+60": (9, 10),
    "+974": (8,), "+966": (9,),
}
_DIAL_CODES = sorted(PHONE_RULES, key=len, reverse=True)


def normalize_phone(phone: str) -> str:
    cleaned = re.sub(r"[\s\-()]", "", phone or "")
    if cleaned and not cleaned.startswith("+"):
        cleaned = "+" + cleaned
    return cleaned


def validate_phone(phone: str) -> str:
    """Returns the normalized E.164 phone or raises ValueError with a friendly message."""
    p = normalize_phone(phone)
    if not re.fullmatch(r"\+\d{7,15}", p):
        raise ValueError("Phone number must contain only digits (7–15) after the country code.")
    for code in _DIAL_CODES:
        if p.startswith(code):
            national = p[len(code):]
            if len(national) not in PHONE_RULES[code]:
                want = " or ".join(str(n) for n in PHONE_RULES[code])
                raise ValueError(f"A {code} number needs {want} digits after the country code (you entered {len(national)}).")
            if national.startswith("0"):
                raise ValueError("Drop the leading 0 from the phone number.")
            return p
    return p


def validate_password(password: str) -> str:
    if len(password or "") < 8:
        raise ValueError("Password must be at least 8 characters.")
    if not re.search(r"[A-Z]", password):
        raise ValueError("Password needs at least one uppercase letter.")
    if not re.search(r"\d", password):
        raise ValueError("Password needs at least one number.")
    return password
