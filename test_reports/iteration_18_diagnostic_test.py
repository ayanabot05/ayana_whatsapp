from pathlib import Path


SERVER = Path("/app/backend/server.py").read_text()
SCHEDULER = Path("/app/backend/scheduler.py").read_text()
ESCALATION = Path("/app/backend/escalation.py").read_text()
WHATSAPP = Path("/app/backend/whatsapp.py").read_text()
PRICING = Path("/app/backend/pricing.py").read_text()
PAYMENTS = Path("/app/backend/payments.py").read_text()
MONTHLY = Path("/app/backend/monthly_report.py").read_text()
ONBOARDING = Path("/app/frontend/src/pages/Onboarding.js").read_text()
DASHBOARD = Path("/app/frontend/src/pages/Dashboard.js").read_text()
TEMPLATES = Path("/app/meta_approved_templates.txt").read_text()


def test_notify_family_uses_free_form_paths_without_delivery_persistence_hooks():
    assert "async def _notify_family" in SERVER
    assert "send_whatsapp(r[\"phone\"], head)" in SERVER
    assert "await send_audio_link(r[\"phone\"], hosted_audio_url)" in SERVER
    assert "if parent is None" in SERVER and "ignoring" in SERVER


def test_signup_welcome_noop_and_duplicate_welcome_paths_exist():
    assert "background_tasks.add_task(send_child_welcome" in SERVER
    assert "async def send_child_welcome" in WHATSAPP
    assert "gated until first parent added" in WHATSAPP
    assert "background_tasks.add_task(send_welcome_for_new_parent" in SERVER
    assert "background_tasks.add_task(send_care_circle_activation_welcome" in SERVER


def test_activation_hardcodes_true_even_if_send_paths_can_fail():
    assert "activated = True" in SERVER
    assert '"welcome_sent": True' in SERVER
    assert "results.append({\"parent\": p.get(\"name\"), \"status\": \"failed\"" in SERVER


def test_scheduler_replays_all_overdue_slots_same_day_simulation():
    # Mirrors scheduler condition: if slot_time > hhmm: continue. No activation-day gate.
    hhmm = "12:00"
    slots = ["08:00", "09:00", "13:00"]
    due = [s for s in slots if not (s > hhmm)]
    assert due == ["08:00", "09:00"]
    assert "if slot_time > hhmm:" in SCHEDULER


def test_scheduler_daily_cap_uses_unfiltered_count_so_failures_can_block_simulation():
    # Query in source has no status filter, so failed rows can fill cap.
    assert "SELECT count(*) FROM message_logs WHERE parent_id = $1 AND day_key = $2" in SCHEDULER
    total_today_from_failed_only = 15
    cap = 15
    blocked = total_today_from_failed_only >= cap
    assert blocked is True


def test_scheduler_fail_count_is_category_level_not_slot_level():
    assert "WHERE parent_id = $1 AND day_key = $2 AND category = $3" in SCHEDULER
    assert "status = 'failed'" in SCHEDULER
    assert "slot_time" not in SCHEDULER.split("status = 'failed'", 1)[1].split("last_fail_at", 1)[0]


def test_scheduler_medicine_dedup_key_omits_medicine_identity():
    assert "WHERE parent_id = $1 AND day_key = $2 AND category = $3" in SCHEDULER
    assert "AND (slot_time IS NULL OR slot_time = $4)" in SCHEDULER
    assert "medicine_id" not in SCHEDULER.split("already_sent", 1)[1].split("fail_stat", 1)[0]


def test_escalation_cap_checked_once_before_retry_loop_only():
    assert "MAX_DAILY_ESCALATIONS = 3" in ESCALATION
    assert "escalation_count_today" in ESCALATION
    assert "for log in logs:" in ESCALATION
    # No re-check inside loop after inserts
    loop_block = ESCALATION.split("for log in logs:", 1)[1].split("# ---- 2) FIRST WARNING", 1)[0]
    assert "escalation_count_today" not in loop_block


def test_reengagement_and_care_watch_vacation_bypass_static_confirmation():
    reengage_block = SCHEDULER.split("async def _check_reengagement_impl", 1)[1]
    assert "vacation_start" not in reengage_block and "vacation_end" not in reengage_block
    assert "vacation_start" not in ESCALATION and "vacation_end" not in ESCALATION


def test_parent_first_warning_uses_plain_text_not_template_helper():
    assert "await asyncio.to_thread(send_whatsapp, parent.get(\"phone\") or \"\", soft_parent)" in ESCALATION
    assert "async def send_first_warning_to_parent" in WHATSAPP
    assert "send_first_warning_to_parent(" not in ESCALATION


def test_warning_templates_are_separate_and_declared():
    assert "async def send_first_warning_to_child" in WHATSAPP
    assert "async def send_main_warning_to_child" in WHATSAPP
    assert "ayana_first_warn_child_en" in TEMPLATES
    assert "ayana_main_warn_child_en" in TEMPLATES
    assert "ayana_first_warn_parent_en" in TEMPLATES


def test_frontend_schedule_bridge_gap_and_pause_mismatch_static():
    assert "api.post(\"/schedules\"" in ONBOARDING
    assert "api.put(`/schedules/" in ONBOARDING
    assert "/health-reminders" not in ONBOARDING and "/routines" not in ONBOARDING and "/medicines" not in ONBOARDING
    assert "toggle-schedule" in DASHBOARD and "api.put(`/schedules/" in DASHBOARD
    assert "FROM parent_checkins" in SCHEDULER and "FROM schedules" not in SCHEDULER


def test_timezone_and_pricing_payment_static_findings():
    assert "timezone: user?.timezone || getBrowserTimezone()" in ONBOARDING
    assert '"INR": {"month": 949, "year": 950}' in PRICING
    assert '"currency": "usd"' in PAYMENTS
    assert 'mode="payment"' in PAYMENTS


def test_reported_lint_baseline_duplicates_static():
    assert MONTHLY.count("from database import get_pool") == 2
    assert MONTHLY.count("def _tz(") == 2
    assert MONTHLY.count("except:") == 4
    assert SERVER.count("CHECKIN_CATEGORIES") >= 2
    assert SERVER.count("async def delete_routine") == 2
