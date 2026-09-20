from datetime import datetime, timezone
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import List, Optional
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from pricing import plan_limits
from validation import validate_phone, validate_password
from templates_data import LANGUAGES

_VALID_LANGUAGE_CODES = {l["code"] for l in LANGUAGES}


def _iana_timezone(value):
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError('Choose the actual IANA timezone for this location.')
    return value


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------- Auth ----------
class RegisterInput(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    email: EmailStr
    phone: str = Field(..., min_length=6, max_length=20)
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("phone")
    @classmethod
    def clean_phone(cls, v: str) -> str:
        return validate_phone(v)

    @field_validator("password")
    @classmethod
    def strong_password(cls, v: str) -> str:
        return validate_password(v)


class ForgotPasswordInput(BaseModel):
    phone: str = Field(..., min_length=6, max_length=20)

    @field_validator("phone")
    @classmethod
    def clean_phone(cls, v: str) -> str:
        return validate_phone(v)


class ResetPasswordInput(BaseModel):
    phone: str = Field(..., min_length=6, max_length=20)
    code: str = Field(..., min_length=4, max_length=8)
    new_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("phone")
    @classmethod
    def clean_phone(cls, v: str) -> str:
        return validate_phone(v)

    @field_validator("new_password")
    @classmethod
    def strong_password(cls, v: str) -> str:
        return validate_password(v)


class ChangePasswordInput(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def strong_password(cls, v: str) -> str:
        return validate_password(v)


class EmailChangeRequestInput(BaseModel):
    new_email: EmailStr
    password: str = Field(..., min_length=1)


class EmailChangeConfirmInput(BaseModel):
    challenge_id: UUID
    code: str = Field(..., min_length=4, max_length=8)


class LoginInput(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)


# ---------- Child profile ----------
class ChildProfileInput(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    phone: str = Field(..., min_length=6, max_length=20)
    city: str = Field(..., min_length=1, max_length=80)
    @field_validator('city')
    @classmethod
    def required_city(cls, value):
        if not value.strip():
            raise ValueError('City is required.')
        return value.strip()
    timezone: str = Field(..., min_length=2, max_length=64)
    _valid_timezone = field_validator('timezone')(_iana_timezone)
    @field_validator("phone")
    @classmethod
    def clean_phone(cls, v: str) -> str:
        return validate_phone(v)


# ---------- Medicine ----------
MEDICINE_SHAPES = {"round", "oval", "capsule", "oblong", "diamond", "square"}
MEDICINE_COLORS = {"white", "cream", "yellow", "orange", "pink", "red", "purple", "blue", "green", "brown", "beige"}
MEDICINE_TIMINGS = {"morning", "afternoon", "evening", "bedtime", "before_food", "after_food", "empty_stomach", "with_food"}


class MedicineItem(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()), max_length=80)
    name: str = Field(..., min_length=1, max_length=80)
    dose: str = Field(..., min_length=1, max_length=60)
    shape: str = Field(..., min_length=1, max_length=20)
    color: str = Field(..., min_length=1, max_length=20)
    timing: Optional[str] = Field(None, max_length=20)
    reminder_time: Optional[str] = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    notes: Optional[str] = Field(None, max_length=200)
    is_recovery: bool = False
    reminder_times: List[str] = Field(default_factory=list, max_length=6)

    @model_validator(mode='after')
    def complete_medicine(self):
        import re
        self.name, self.dose = self.name.strip(), self.dose.strip()
        if not self.name or not self.dose:
            raise ValueError('Medicine name and dose/quantity are required.')
        if not self.reminder_times and self.reminder_time:
            self.reminder_times = [self.reminder_time]
        if not self.reminder_times or any(not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', t) for t in self.reminder_times):
            raise ValueError('Choose a valid medicine reminder time.')
        self.reminder_times = sorted(set(self.reminder_times))
        self.reminder_time = self.reminder_times[0]
        if not self.timing and not (self.notes or '').strip():
            raise ValueError('Add the medicine instructions provided to your parent.')
        return self

    @field_validator("shape")
    @classmethod
    def valid_shape(cls, v):
        if v and v not in MEDICINE_SHAPES:
            raise ValueError(f"shape must be one of: {', '.join(sorted(MEDICINE_SHAPES))}")
        return v

    @field_validator("color")
    @classmethod
    def valid_color(cls, v):
        if v and v not in MEDICINE_COLORS:
            raise ValueError(f"color must be one of: {', '.join(sorted(MEDICINE_COLORS))}")
        return v

    @field_validator("timing")
    @classmethod
    def valid_timing(cls, v):
        if v and v not in MEDICINE_TIMINGS:
            raise ValueError(f"timing must be one of: {', '.join(sorted(MEDICINE_TIMINGS))}")
        return v


# ---------- Habits ----------
class HabitsInput(BaseModel):
    wake_time: Optional[str] = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    tea_time: Optional[str] = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    tea_type: Optional[str] = Field("tea", pattern="^(tea|coffee)$")
    walk_time: Optional[str] = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    lunch_time: Optional[str] = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    dinner_time: Optional[str] = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    sleep_time: Optional[str] = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


# ---------- Parent profile ----------
VALID_CATEGORIES = {
    "morning_wish", "breakfast", "lunch", "dinner", "afternoon_checkin",
    "tea_check", "walk_check",
    "medicine", "water", "bp_check", "sugar_check", "health_check",
    "how_feeling", "goodnight", "love_note",
    "office_return", "market_return", "shopping_return", "temple_return", "outing_return",
}


class ParentInput(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    preferred_name: Optional[str] = Field(None, max_length=40)
    relationship: str = Field(..., pattern="^(mother|father)$")
    phone: str = Field(..., min_length=6, max_length=20)
    language: str = Field(..., min_length=2, max_length=8)
    timezone: str = Field(..., min_length=2, max_length=64)
    _valid_timezone = field_validator('timezone')(_iana_timezone)
    city: str = Field(..., min_length=1, max_length=80)
    @field_validator('city')
    @classmethod
    def required_city(cls, value):
        if not value.strip():
            raise ValueError('Parent city is required.')
        return value.strip()
    other_parent_name: Optional[str] = Field(None, max_length=40)
    notes: Optional[str] = Field(None, max_length=300)
    birthday: Optional[str] = Field(None, pattern=r"^(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")

    nicknames: List[str] = Field(default_factory=list)
    habits: Optional[HabitsInput] = None
    medicine_list: Optional[List[MedicineItem]] = Field(default_factory=list)
    stories: Optional[List[str]] = Field(default_factory=list, max_length=5)
    # Activity window — auto-learned from historical reply patterns.
    # When set, outbound messages are deferred if sent outside this window.
    activity_window_start: Optional[str] = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    activity_window_end: Optional[str] = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    auto_activity_detection: bool = False
    # #9 Vacation / holiday mode — paused date range (YYYY-MM-DD, parent-local).
    vacation_start: Optional[str] = Field(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")
    vacation_end: Optional[str] = Field(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")

    @field_validator("phone")
    @classmethod
    def clean_phone(cls, v: str) -> str:
        return validate_phone(v)

    @field_validator("language")
    @classmethod
    def valid_language(cls, v):
        if v not in _VALID_LANGUAGE_CODES:
            raise ValueError(f"language must be one of: {', '.join(sorted(_VALID_LANGUAGE_CODES))}")
        return v

    @field_validator("nicknames")
    @classmethod
    def limit_nicknames(cls, v):
        if len(v) > 3:
            raise ValueError("Max 3 nicknames — plan-level limit is enforced separately")
        return [n.strip() for n in v if n.strip()]

    @field_validator("stories")
    @classmethod
    def limit_stories(cls, v):
        return [s.strip() for s in (v or []) if s.strip()][:5]

    @field_validator("birthday", mode="before")
    @classmethod
    def blank_birthday_to_none(cls, v):
        # Frontend sends "" (not omitted) when the optional birthday date
        # picker is left blank — without this, the MM-DD pattern check
        # rejects "" with a 422 and silently breaks parent create/update
        # for anyone who doesn't set a birthday.
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        return v

    @field_validator("activity_window_start", "activity_window_end", "vacation_start", "vacation_end", mode="before")
    @classmethod
    def blank_activity_window_to_none(cls, v):
        # Same fix as birthday above — the DND start/end time pickers send
        # "" when left blank, which fails the HH:MM pattern check with a
        # 422 and breaks saving for any parent who doesn't set a quiet
        # window. Both fields are optional, so "" should just mean unset.
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        return v


# ---------- Schedule ----------
class ScheduleMessage(BaseModel):
    active: bool = True
    time: str = Field(..., pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    category: str = Field(..., min_length=1, max_length=40)
    type: Optional[str] = Field(None, max_length=20)
    custom_text: Optional[str] = Field(None, max_length=500)
    source: Optional[str] = Field(None, max_length=20)
    medicine_id: Optional[str] = Field(None, max_length=80)
    weekdays: List[int] = Field(default_factory=lambda: list(range(7)), min_length=1, max_length=7)
    location_label: Optional[str] = Field(None, max_length=80)

    @field_validator('weekdays')
    @classmethod
    def valid_days(cls, value):
        if any(d < 0 or d > 6 for d in value):
            raise ValueError('Choose weekdays from Monday to Sunday.')
        return sorted(set(value))

    @field_validator("category")
    @classmethod
    def valid_category(cls, v):
        if v not in VALID_CATEGORIES:
            raise ValueError(f"category must be one of: {', '.join(sorted(VALID_CATEGORIES))}")
        return v


class ScheduleInput(BaseModel):
    parent_id: str
    mode: str = Field("nitya", pattern="^(nitya|bandham|raksha)$")
    messages: List[ScheduleMessage]
    active: bool = True
    recovery_mode: bool = False
    recovery_until: Optional[str] = None
    reengagement_hours: int = Field(1, ge=1, le=24)

    @model_validator(mode='after')
    def limit_messages(self):
        from templates_data import category_type
        limits = plan_limits(self.mode)
        if not self.messages:
            raise ValueError("Add at least 1 daily check-in")
        extra = limits.get('recovery_extra_reminders', 0) if self.recovery_mode and limits.get('recovery_mode') else 0
        budgets = {'checkin': limits['checkins'], 'reminder': limits['reminders'] + extra, 'activity': limits.get('activities', 0), 'safety': 1, 'water': 1}
        seen = set()
        for m in self.messages:
            identity = (m.category, m.time, m.medicine_id, tuple(m.weekdays))
            if identity in seen:
                raise ValueError('Remove the duplicate reminder at the same time.')
            seen.add(identity)
        for day in range(7):
            counts = dict.fromkeys(budgets, 0)
            for m in self.messages:
                if m.active and day in m.weekdays:
                    counts['water' if m.category == 'water' else category_type(m.category)] += 1
            for kind, count in counts.items():
                if count > budgets[kind]:
                    raise ValueError(f'This plan allows {budgets[kind]} {kind} reminders per day. Every saved reminder must fit.')
        return self


# ---------- Recovery mode (Raksha) ----------
class RecoveryStartInput(BaseModel):
    extra_reminders: List[ScheduleMessage] = Field(..., min_length=1, max_length=4)
    days: Optional[int] = Field(None, ge=1, le=90)


# ---------- Preferences ----------
class PreferencesInput(BaseModel):
    emergency_keywords: Optional[List[str]] = None
    daily_summary: Optional[bool] = None
    email_notifications: Optional[bool] = None
    whatsapp_reports: Optional[bool] = None


# ---------- Consent ----------
class ConsentInput(BaseModel):
    consent_type: str = Field(..., pattern="^(child|parent)$")
    agreed: bool
    text: str = Field(..., max_length=500)


# ---------- Emergency contacts (distinct from Care Circle) ----------
class EmergencyContact(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    phone: str = Field(..., min_length=6, max_length=20)
    relation: Optional[str] = Field(None, max_length=40)

    @field_validator("phone")
    @classmethod
    def clean_phone(cls, v: str) -> str:
        return validate_phone(v)


class EmergencyContactsInput(BaseModel):
    contacts: List[EmergencyContact] = Field(default_factory=list, max_length=5)


# ---------- Two-way moment (child -> parent) ----------
class MomentInput(BaseModel):
    parent_id: str
    text: str = Field(..., min_length=1, max_length=600)
    image_url: Optional[str] = Field(None, max_length=600)
    image_urls: List[str] = Field(default_factory=list, max_length=2)


# ── Request payload models consolidated from server.py (refactor slice 0) ──
class CheckoutInput(BaseModel):
    plan: str = Field("nitya", pattern="^(nitya|bandham|raksha|basic|care_plus)$")
    billing: str = Field("month", pattern="^(month|year)$")
    currency: str = Field("INR", pattern="^(INR|USD|GBP|EUR|AED|SGD|AUD|CAD)$")
    origin_url: str = ""


class SendTestInput(BaseModel):
    parent_id: str
    category: str = "how_feeling"


class PreviewInput(BaseModel):
    parent_id: str
    category: str = "how_feeling"


class InviteInput(BaseModel):
    email: str
    parent_id: str = ""


class AnalyticsEventInput(BaseModel):
    type: Optional[str] = None
    name: Optional[str] = None
    page: Optional[str] = None
    path: Optional[str] = None



class VacationInput(BaseModel):
    start: Optional[str] = Field(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")
    end: Optional[str] = Field(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")

    @field_validator("start", "end", mode="before")
    @classmethod
    def blank_to_none(cls, v):
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        return v


class EmergencyEventUpdate(BaseModel):
    status: str = Field(..., pattern="^(open|reviewed|resolved|false_positive)$")
    resolution_note: Optional[str] = None


class SiblingOtpInput(BaseModel):
    email: EmailStr
    name: str = Field(..., min_length=1, max_length=80)
    phone: str = Field(..., min_length=6, max_length=20)
    language: str = Field("en", min_length=2, max_length=8)
    relation: str = Field("sibling", max_length=20)


class SiblingVerifyInput(SiblingOtpInput):
    challenge_id: UUID
    code: str = Field(..., min_length=4, max_length=8)


class MarkRepliesReadInput(BaseModel):
    ids: Optional[List[str]] = None  # None/empty → mark ALL of the user's replies read


class SimulateReplyInput(BaseModel):
    parent_id: str
    text: str = ""
    num_media: int = Field(0, ge=0)
    button_payload: Optional[str] = None
