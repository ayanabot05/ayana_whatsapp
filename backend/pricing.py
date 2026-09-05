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
            "checkins": 2,                 # morning + evening
            "reminders": 2,                # medicine
            "templates_per_day": 4,
            "nicknames_max": 2,
            "variants_per_slot": 3,
            "recovery_mode": False,
        },
        "price": {
            "INR": {"month": 149, "year": 1430},
            "USD": {"month": 10, "year": 100},
            "GBP": {"month": 8.99, "year": 89},
            "EUR": {"month": 10, "year": 100},
            "AED": {"month": 36, "year": 360},
            "SGD": {"month": 13.99, "year": 139},
            "AUD": {"month": 15.99, "year": 159},
            "CAD": {"month": 13.99, "year": 139},
        },
        "features": [
            "1 parent — Amma or Nanna",
            "2 daily check-ins + 2 medicine reminders = 4 daily touches",
            "2 nicknames, 3 rotating message variants per slot",
            "Tap-only Telugu/Hindi/English buttons",
            "Solo child account",
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
            "checkins": 3,
            "reminders": 3,
            "templates_per_day": 6,
            "nicknames_max": 3,
            "variants_per_slot": 7,
            "recovery_mode": False,
        },
        "price": {
            "INR": {"month": 299, "year": 2870},
            "USD": {"month": 19, "year": 190},
            "GBP": {"month": 16.99, "year": 169},
            "EUR": {"month": 19, "year": 190},
            "AED": {"month": 69, "year": 690},
            "SGD": {"month": 25.99, "year": 259},
            "AUD": {"month": 28.99, "year": 289},
            "CAD": {"month": 25.99, "year": 259},
        },
        "features": [
            "2 parents — Amma & Nanna",
            "3 daily check-ins + 3 medicine reminders = 6 daily touches",
            "3 nicknames, 7 rotating message variants per slot",
            "Seasonal greetings, tea/walk habit check-ins",
            "Solo child account",
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
            "reminders": 4,               # 3-4 base, +extra during recovery
            "templates_per_day": 8,
            "nicknames_max": 3,
            "variants_per_slot": 7,
            "recovery_mode": True,
            "recovery_extra_reminders": 2,  # additional slots during recovery
            "recovery_days": 30,
        },
        "price": {
            "INR": {"month": 429, "year": 4120},
            "USD": {"month": 29, "year": 290},
            "GBP": {"month": 25.99, "year": 259},
            "EUR": {"month": 29, "year": 290},
            "AED": {"month": 106, "year": 1060},
            "SGD": {"month": 39.99, "year": 399},
            "AUD": {"month": 44.99, "year": 449},
            "CAD": {"month": 39.99, "year": 399},
        },
        "features": [
            "2 parents + Care Circle for 2 more kids",
            "4 daily check-ins + 3-4 medicine reminders = 7-8 daily touches",
            "Pre/post-surgery recovery mode — extra reminder slots for 30 days",
            "3 nicknames, 7 rotating message variants per slot",
            "Monthly report + mood graph, shared with both kids",
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
