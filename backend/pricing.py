"""
pricing.py — AYANA v2 plans: Nitya / Bandham / Raksha

Every tier steps up on BOTH quantity (touches, kids, medicines) and
quality (nicknames, message variants, report depth) — no tier gives
away the full personalization engine for free.

Payments are still flag-gated (PAYMENTS_ENABLED) — this module is
presentation + limit config + cost control, same as v1.
"""

CURRENCIES = [
    {"code": "INR", "symbol": "₹", "label": "India (INR)"},
    {"code": "USD", "symbol": "$", "label": "USD"},
    {"code": "GBP", "symbol": "£", "label": "UK (GBP)"},
    {"code": "EUR", "symbol": "€", "label": "Europe (EUR)"},
    {"code": "AED", "symbol": "AED ", "label": "UAE (AED)"},
    {"code": "SGD", "symbol": "S$", "label": "Singapore (SGD)"},
    {"code": "AUD", "symbol": "A$", "label": "Australia (AUD)"},
    {"code": "CAD", "symbol": "C$", "label": "Canada (CAD)"},
]

PLANS = [
    {
        "id": "nitya",
        "name": "AYANA Nitya",
        "tagline": "Everyday closeness — one parent, done simply",
        "highlight": False,
        "limits": {
            "parents": 1,
            "family_members": 0,
            "checkins": 3,
            "reminders": 3,
            "activities": 1,
            "templates_per_day": 7,
            "nicknames_max": 2,
            "variants_per_slot": 3,
            "recovery_mode": False,
        },
        "price": {
            "INR": {"month": 949, "year": 9490},
            "USD": {"month": 9.99, "year": 99.90},
            "GBP": {"month": 7.99, "year": 79.90},
            "EUR": {"month": 9.99, "year": 99.90},
            "AED": {"month": 36.99, "year": 369.90},
            "SGD": {"month": 13.99, "year": 139.90},
            "AUD": {"month": 15.99, "year": 159.90},
            "CAD": {"month": 13.99, "year": 139.90},
        },
        "features": [
            "1 parent — Amma or Nanna",
            "3 daily check-ins + 3 medicine reminders + 1 daily activity",
            "2 nicknames, 3 rotating message variants per slot",
            "Tap-only Telugu / Hindi / English buttons",
            "1 child account",
            "Monthly report",
        ],
    },
    {
        "id": "bandham",
        "name": "AYANA Bandham",
        "tagline": "The bond that holds — two parents, full personality",
        "highlight": True,
        "limits": {
            "parents": 2,
            "family_members": 0,
            "checkins": 4,
            "reminders": 4,
            "activities": 2,
            "templates_per_day": 10,
            "nicknames_max": 3,
            "variants_per_slot": 7,
            "recovery_mode": False,
        },
        "price": {
            "INR": {"month": 1799, "year": 17990},
            "USD": {"month": 19.99, "year": 199.90},
            "GBP": {"month": 15.99, "year": 159.90},
            "EUR": {"month": 19.99, "year": 199.90},
            "AED": {"month": 69.99, "year": 699.90},
            "SGD": {"month": 26.99, "year": 269.90},
            "AUD": {"month": 29.99, "year": 299.90},
            "CAD": {"month": 26.99, "year": 269.90},
        },
        "features": [
            "2 parents — Amma & Nanna",
            "4 daily check-ins + 4 medicine reminders + 2 daily activities",
            "3 nicknames, 7 rotating message variants per slot",
            "Seasonal greetings, tea / walk / water routine nudges",
            "1 child account",
            "Monthly report + mood graph with analysis",
        ],
    },
    {
        "id": "raksha",
        "name": "AYANA Raksha",
        "tagline": "Full protection — the whole family, covered",
        "highlight": False,
        "limits": {
            "parents": 2,
            "family_members": 2,
            "checkins": 4,
            "reminders": 6,
            "activities": 4,
            "templates_per_day": 14,
            "nicknames_max": 3,
            "variants_per_slot": 7,
            "recovery_mode": True,
            "recovery_extra_reminders": 2,
            "recovery_days": 30,
        },
        "price": {
            "INR": {"month": 2749, "year": 27490},
            "USD": {"month": 29.99, "year": 299.90},
            "GBP": {"month": 24.99, "year": 249.90},
            "EUR": {"month": 29.99, "year": 299.90},
            "AED": {"month": 109.99, "year": 1099.90},
            "SGD": {"month": 39.99, "year": 399.90},
            "AUD": {"month": 44.99, "year": 449.90},
            "CAD": {"month": 39.99, "year": 399.90},
        },
        "features": [
            "2 parents + Care Circle for up to 2 more children (3 in total)",
            "4 daily check-ins + 6 medicine reminders + 4 daily activities",
            "Pre / post-surgery recovery mode — extra reminder slots for 30 days",
            "3 nicknames, 7 rotating message variants per slot",
            "Monthly report + mood graph, shared with the whole Care Circle",
        ],
    },
]

PLAN_BY_ID = {p["id"]: p for p in PLANS}

# Backward-compat aliases so old data (mode: "basic"/"care_plus") doesn't 500
_LEGACY_ALIASES = {"basic": "nitya", "care_plus": "bandham"}

def resolve_plan_id(plan_id: str) -> str:
    return _LEGACY_ALIASES.get(plan_id, plan_id) if plan_id not in PLAN_BY_ID else plan_id

def plan_limits(plan_id: str) -> dict:
    """Get limits for a plan — used by scheduler.py / models.py validation."""
    plan_id = resolve_plan_id(plan_id)
    plan = PLAN_BY_ID.get(plan_id) or PLAN_BY_ID["nitya"]
    return plan["limits"]

def get_template_cost_estimate(plan_id: str) -> dict:
    """
    WhatsApp cost estimate: if parent taps once a day, only the first
    message is a paid template; everything after is a free in-session
    quick-reply until the 24h session window closes.
    """
    limits = plan_limits(plan_id)
    total_scheduled = limits["checkins"] + limits["reminders"]
    return {
        "total_scheduled": total_scheduled,
        "paid_best_case": 1,
        "paid_worst_case": total_scheduled,
        "free_quick_replies_best_case": total_scheduled - 1,
    }