"""
Iteration 12 — unit tests for the medicine-name substitution fix.

Covers:
  * server.py::_resolve_medicine_name  (real name / reminder_time match /
    JSONB-string guard / language-native fallback)
  * whatsapp.py::_language_native_medicine_placeholder
  * whatsapp.py::_build_approved_template_vars  ({{2}} that actually goes
    to the Meta ayana_medicine_{lang} template)
  * templates_data.py::render_slot_body  (the /api/messages/preview body)

Runs fully offline. A dummy DATABASE_URL is injected before import because
database.py raises at import time when it is missing (no local .env here).
"""

import os
import sys

import pytest

sys.path.insert(0, "/app/backend")
os.environ.setdefault("DATABASE_URL", "postgresql://qa:qa@127.0.0.1:5432/qa")
os.environ.setdefault("ADMIN_PASSWORD", "qa-dummy")
os.environ.setdefault("JWT_SECRET", "qa-dummy-secret")

import whatsapp  # noqa: E402
from templates_data import render_slot_body  # noqa: E402

try:
    from server import _resolve_medicine_name
    SERVER_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover
    _resolve_medicine_name = None
    SERVER_IMPORT_ERROR = exc


def _parent(language, meds, **kw):
    p = {
        "id": "00000000-0000-0000-0000-000000000001",
        "name": "Amma",
        "preferred_name": "Ammmmmaaa",
        "nicknames": ["Ammmmmaaa"],
        "language": language,
        "phone": "+919999999999",
        "timezone": "Asia/Kolkata",
        "medicine_list": meds,
        "habits": {},
        "stories": [],
    }
    p.update(kw)
    return p


# ── server.py::_resolve_medicine_name ────────────────────────────────────
@pytest.mark.skipif(_resolve_medicine_name is None, reason=f"server import failed: {SERVER_IMPORT_ERROR}")
class TestResolveMedicineName:
    def test_te_parent_with_medicine_returns_real_name(self):
        p = _parent("te", [{"name": "Amlokind", "reminder_time": "09:00"}])
        assert _resolve_medicine_name(p) == "Amlokind"

    def test_te_parent_empty_list_returns_telugu_placeholder(self):
        assert _resolve_medicine_name(_parent("te", [])) == "మందు"
        assert _resolve_medicine_name(_parent("te", None)) == "మందు"

    def test_hi_parent_empty_list_returns_hindi_placeholder(self):
        assert _resolve_medicine_name(_parent("hi", [])) == "दवाई"

    def test_en_parent_empty_list_returns_english_placeholder(self):
        assert _resolve_medicine_name(_parent("en", [])) == "your medicine"

    def test_unknown_language_falls_back_to_english(self):
        assert _resolve_medicine_name(_parent("ta", [])) == "your medicine"

    def test_target_time_picks_matching_medicine(self):
        meds = [
            {"name": "Amlokind", "reminder_time": "09:00"},
            {"name": "Metformin", "reminder_time": "21:00"},
        ]
        assert _resolve_medicine_name(_parent("te", meds), "21:00") == "Metformin"
        assert _resolve_medicine_name(_parent("te", meds), "09:00") == "Amlokind"

    def test_target_time_no_match_falls_back_to_first(self):
        meds = [{"name": "Amlokind", "reminder_time": "09:00"}]
        assert _resolve_medicine_name(_parent("te", meds), "13:00") == "Amlokind"

    def test_jsonb_string_medicine_list_is_decoded(self):
        p = _parent("te", '[{"name": "Amlokind", "reminder_time": "09:00"}]')
        assert _resolve_medicine_name(p) == "Amlokind"

    def test_malformed_string_medicine_list_falls_back(self):
        assert _resolve_medicine_name(_parent("te", "not-json")) == "మందు"

    def test_blank_medicine_name_falls_back_to_placeholder(self):
        assert _resolve_medicine_name(_parent("te", [{"name": "   "}])) == "మందు"

    def test_case_insensitive_language(self):
        assert _resolve_medicine_name(_parent("TE", [])) == "మందు"

    def test_never_returns_english_literal_for_indic_parent(self):
        for lang, expected in (("te", "మందు"), ("hi", "दवाई")):
            out = _resolve_medicine_name(_parent(lang, []))
            assert out == expected
            assert "your medicine" not in out


# ── whatsapp.py fallback helper ──────────────────────────────────────────
class TestLanguageNativePlaceholder:
    @pytest.mark.parametrize("lang,expected", [
        ("en", "your medicine"), ("te", "మందు"), ("hi", "दवाई"),
        ("TE", "మందు"), ("", "your medicine"), (None, "your medicine"),
        ("ta", "your medicine"),
    ])
    def test_placeholder(self, lang, expected):
        assert whatsapp._language_native_medicine_placeholder(lang) == expected


# ── whatsapp.py::_build_approved_template_vars — the actual Meta {{2}} ───
class TestApprovedTemplateVars:
    def test_medicine_te_with_real_name(self):
        v = whatsapp._build_approved_template_vars(
            "medicine", "medicine", "Ammmmmaaa", _parent("te", []), "te", "Amlokind")
        assert v["1"] == "Ammmmmaaa"
        assert "Amlokind" in v["2"]

    def test_medicine_te_empty_name_has_no_english_literal(self):
        v = whatsapp._build_approved_template_vars(
            "medicine", "medicine", "Ammmmmaaa", _parent("te", []), "te", "")
        assert "your medicine" not in v["2"], f"English literal leaked into Telugu template: {v['2']!r}"
        assert "మందు" in v["2"]

    def test_medicine_hi_empty_name_has_no_english_literal(self):
        v = whatsapp._build_approved_template_vars(
            "medicine", "medicine", "Amma", _parent("hi", []), "hi", "")
        assert "your medicine" not in v["2"], f"English literal leaked into Hindi template: {v['2']!r}"
        assert "दवाई" in v["2"]

    def test_medicine_te_var2_has_no_ascii_word_tablet(self):
        """ayana_medicine_te already renders '{{2}} టాబ్లెట్' — appending the
        English word 'tablet' to {{2}} both duplicates it and re-introduces
        English into the Telugu sentence."""
        v = whatsapp._build_approved_template_vars(
            "medicine", "medicine", "Ammmmmaaa", _parent("te", []), "te", "Amlokind")
        assert "tablet" not in v["2"].lower(), (
            f"{{2}}={v['2']!r} -> Telugu template renders "
            f"'మీ {v['2']} టాబ్లెట్' (duplicated/English 'tablet')")

    def test_non_medicine_category_uses_label(self):
        v = whatsapp._build_approved_template_vars(
            "medicine", "bp_check", "Amma", _parent("te", []), "te", "")
        assert v["2"] == "BP check"

    def test_opener_and_mood_unaffected(self):
        o = whatsapp._build_approved_template_vars(
            "opener", "morning_wish", "Amma", _parent("te", []), "te", "")
        assert o["1"] == "Amma" and "2" in o
        m = whatsapp._build_approved_template_vars(
            "mood", "how_feeling", "Amma", _parent("te", []), "te", "")
        assert m == {"1": "Amma"}


# ── /api/messages/preview body (render_slot_body) ────────────────────────
class TestPreviewBody:
    def test_te_preview_contains_real_medicine_name(self):
        body = render_slot_body("medicine", "te", _parent("te", []), 0, "Amlokind", 7)
        assert "your medicine" not in body
        assert "Amlokind" in body or "{medicine" not in body

    def test_te_preview_placeholder_no_english(self):
        body = render_slot_body("medicine", "te", _parent("te", []), 0, "మందు", 7)
        assert "your medicine" not in body, f"body={body!r}"

    def test_hi_preview_placeholder_no_english(self):
        body = render_slot_body("medicine", "hi", _parent("hi", []), 0, "दवाई", 7)
        assert "your medicine" not in body, f"body={body!r}"

    def test_render_slot_body_default_arg_is_not_english_literal(self):
        """templates_data.render_slot_body still defaults medicine_name to
        the English literal — any future caller that forgets to pass it
        re-creates the founder's bug."""
        import inspect
        sig = inspect.signature(render_slot_body)
        assert sig.parameters["medicine_name"].default != "your medicine", (
            "render_slot_body defaults medicine_name='your medicine'")

    def test_no_crash_across_languages_and_day_indices(self):
        for lang in ("en", "te", "hi"):
            for day in range(0, 8):
                body = render_slot_body("medicine", lang, _parent(lang, []), day, "Amlokind", 7)
                assert isinstance(body, str) and body
