"""AYANA schedules; extracted without changing API behaviour."""
import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from fastapi import Depends, APIRouter, HTTPException, Query
from database import get_pool
from models import ScheduleInput, RecoveryStartInput
from medicine_sync import sync_medicine_reminders
from auth import serialize, get_current_user, validate_csrf_token
from templates_data import category_type
from pricing import plan_limits
from services.deps import audit, scope, _get_plan_id


router = APIRouter()


# ---------------- Schedules ----------------
@router.get("/schedules")
async def list_schedules(user: dict = Depends(get_current_user)):
    async with get_pool().acquire() as conn:
        docs = await conn.fetch(
            "select * from schedules where user_id = $1 and deleted_at is null limit 50", scope(user)
        )
    return [serialize(d) for d in docs]

async def _validate_by_plan(user, messages):
    plan_id = await _get_plan_id(user)
    limits = plan_limits(plan_id)
    if not messages:
        raise HTTPException(status_code=400, detail="Add at least one daily check-in.")
    checkins = sum(1 for m in messages if category_type(m.category) == "checkin")
    reminders = sum(1 for m in messages if category_type(m.category) == "reminder")
    if checkins > limits["checkins"]:
        raise HTTPException(status_code=400, detail=f"Your plan allows up to {limits['checkins']} daily check-ins. Upgrade for more.")
    if reminders > limits["reminders"]:
        raise HTTPException(status_code=400, detail=f"Your plan allows up to {limits['reminders']} reminders. Upgrade for more.")
    return plan_id

@router.post("/schedules")
async def create_schedule(payload: ScheduleInput, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    async with get_pool().acquire() as conn:
        parent = await conn.fetchrow(
            "select * from parents where id = $1::uuid and user_id = $2", payload.parent_id, scope(user)
        )
        if not parent:
            raise HTTPException(status_code=404, detail="Parent not found")
        plan_id = await _validate_by_plan(user, payload.messages)
        messages = [m.model_dump() for m in payload.messages]

        row = await conn.fetchrow(
            """
            insert into schedules (user_id, parent_id, mode, messages, active, recovery_mode,
                                    recovery_until, reengagement_hours, created_at, deleted_at)
            values ($1, $2::uuid, $3, $4::jsonb, $5, $6, $7, $8, now(), null)
            returning *
            """,
            scope(user), payload.parent_id, payload.mode, json.dumps(messages), payload.active,
            payload.recovery_mode, payload.recovery_until, payload.reengagement_hours,
        )

        medicine_list = parent["medicine_list"]
        medicine_list = json.loads(medicine_list) if isinstance(medicine_list, str) else (medicine_list or [])
        sync_result = sync_medicine_reminders(
            medicine_list=medicine_list,
            existing_messages=messages,
            plan_id=plan_id,
        )
        await conn.execute(
            "update schedules set messages = $1::jsonb where id = $2",
            json.dumps(sync_result["messages"]), row["id"],
        )
        await conn.execute(
            "update users set onboarding_step = greatest(onboarding_step, 4) where id = $1", user["id"]
        )
        final_row = await conn.fetchrow("select * from schedules where id = $1", row["id"])

    await audit(user["id"], "create_schedule", {"schedule_id": str(row["id"])})
    out = serialize(final_row)
    if sync_result["dropped"]:
        out["medicine_reminders_dropped"] = sync_result["dropped"]
    return out

@router.put("/schedules/{schedule_id}")
async def update_schedule(schedule_id: str, payload: ScheduleInput, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    async with get_pool().acquire() as conn:
        sched = await conn.fetchrow(
            "select * from schedules where id = $1::uuid and user_id = $2", schedule_id, scope(user)
        )
        if not sched:
            raise HTTPException(status_code=404, detail="Schedule not found")
        plan_id = await _validate_by_plan(user, payload.messages)
        parent = await conn.fetchrow("select * from parents where id = $1", sched["parent_id"])
        new_messages = [m.model_dump() for m in payload.messages]

        medicine_list = (parent or {}).get("medicine_list") if parent else []
        medicine_list = json.loads(medicine_list) if isinstance(medicine_list, str) else (medicine_list or [])
        sync_result = sync_medicine_reminders(
            medicine_list=medicine_list,
            existing_messages=new_messages,
            plan_id=plan_id,
        )
        await conn.execute(
            """
            update schedules
            set mode = $1, messages = $2::jsonb, active = $3, recovery_mode = $4,
                recovery_until = $5, reengagement_hours = $6
            where id = $7::uuid
            """,
            payload.mode, json.dumps(sync_result["messages"]), payload.active, payload.recovery_mode,
            payload.recovery_until, payload.reengagement_hours, schedule_id,
        )
        updated = await conn.fetchrow("select * from schedules where id = $1::uuid", schedule_id)

    out = serialize(updated)
    if sync_result["dropped"]:
        out["medicine_reminders_dropped"] = sync_result["dropped"]
    return out

@router.delete("/schedules/{schedule_id}")
async def delete_schedule(schedule_id: str, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    async with get_pool().acquire() as conn:
        await conn.execute(
            "update schedules set deleted_at = now(), active = false where id = $1::uuid and user_id = $2",
            schedule_id, scope(user),
        )
    return {"ok": True}

# ---------------- Recovery mode (Raksha) ----------------
@router.post("/schedules/{schedule_id}/recovery/start")
async def start_recovery(schedule_id: str, payload: RecoveryStartInput, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    async with get_pool().acquire() as conn:
        sched = await conn.fetchrow(
            "select * from schedules where id = $1::uuid and user_id = $2 and deleted_at is null",
            schedule_id, scope(user),
        )
        if not sched:
            raise HTTPException(status_code=404, detail="Schedule not found")
        plan_id = await _get_plan_id(user)
        limits = plan_limits(plan_id)
        if not limits.get("recovery_mode"):
            raise HTTPException(status_code=403, detail="Recovery mode is available on the Raksha plan.")
        max_extra = limits.get("recovery_extra_reminders", 2)
        if len(payload.extra_reminders) > max_extra:
            raise HTTPException(status_code=400, detail=f"Recovery mode allows up to {max_extra} extra reminders.")
        days = payload.days or limits.get("recovery_days", 30)
        until = (date.today() + timedelta(days=days)).isoformat()
        messages = sched["messages"]
        messages = json.loads(messages) if isinstance(messages, str) else (messages or [])
        base_msgs = [m for m in messages if not m.get("is_recovery")]
        extra = [{"time": m.time, "category": m.category, "type": "reminder", "is_recovery": True} for m in payload.extra_reminders]
        await conn.execute(
            "update schedules set messages = $1::jsonb, recovery_mode = true, recovery_until = $2 where id = $3::uuid",
            json.dumps(base_msgs + extra), until, schedule_id,
        )
        updated = await conn.fetchrow("select * from schedules where id = $1::uuid", schedule_id)
    await audit(user["id"], "recovery_start", {"schedule_id": schedule_id, "days": days, "extra": len(extra)})
    return {"ok": True, "recovery_until": until, "schedule": serialize(updated)}

@router.post("/schedules/{schedule_id}/recovery/end")
async def end_recovery(schedule_id: str, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    async with get_pool().acquire() as conn:
        sched = await conn.fetchrow(
            "select * from schedules where id = $1::uuid and user_id = $2 and deleted_at is null",
            schedule_id, scope(user),
        )
        if not sched:
            raise HTTPException(status_code=404, detail="Schedule not found")
        messages = sched["messages"]
        messages = json.loads(messages) if isinstance(messages, str) else (messages or [])
        active_messages = [m for m in messages if not m.get("is_recovery")]
        recovery_messages = [m for m in messages if m.get("is_recovery")]
        await conn.execute(
            """
            update schedules
            set messages = $1::jsonb, recovery_mode = false, recovery_until = null,
                archived_recovery_messages = $2::jsonb
            where id = $3::uuid
            """,
            json.dumps(active_messages), json.dumps(recovery_messages), schedule_id,
        )
    await audit(user["id"], "recovery_end", {"schedule_id": schedule_id, "archived": len(recovery_messages)})
    return {"ok": True, "archived": len(recovery_messages)}


# ═══════════════ NEW: GRANULAR CHECK-INS / HEALTH REMINDERS / ROUTINES ═════
# NOTE: define this against your real category list before shipping — this
# is inferred from templates_data.public_categories() / _CATEGORY_LABEL and
# is NOT guaranteed to match your product's actual check-in categories.
GRANULAR_CHECKIN_CATEGORIES = {
    "morning_wish", "breakfast", "lunch", "dinner",
    "afternoon_checkin", "goodnight", "love_note"
}

# ─── GRANULAR CHECK-INS ────────────────────────────────────────────────

@router.get("/parents/{parent_id}/checkins")
async def list_checkins(parent_id: str, user: dict = Depends(get_current_user)):
    """List all active check‑ins for a parent."""
    async with get_pool().acquire() as conn:
        parent = await conn.fetchrow(
            "SELECT * FROM parents WHERE id = $1::uuid AND user_id = $2 AND deleted_at IS NULL",
            parent_id, scope(user),
        )
        if not parent:
            raise HTTPException(status_code=404, detail="Parent not found")
        rows = await conn.fetch(
            "SELECT * FROM parent_checkins WHERE parent_id = $1::uuid AND is_active = TRUE ORDER BY time",
            parent_id,
        )
    return [serialize(r) for r in rows]


@router.post("/parents/{parent_id}/checkins")
async def add_checkin(parent_id: str, payload: dict, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    """Add or update a check‑in (replaces if category already exists)."""
    category = payload.get("category")
    time_str = payload.get("time")  # "08:00"
    if not category or not time_str:
        raise HTTPException(status_code=400, detail="category and time required")
    if category not in GRANULAR_CHECKIN_CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category. Must be one of: {', '.join(GRANULAR_CHECKIN_CATEGORIES)}"
        )
    async with get_pool().acquire() as conn:
        parent = await conn.fetchrow(
            "SELECT * FROM parents WHERE id = $1::uuid AND user_id = $2 AND deleted_at IS NULL",
            parent_id, scope(user),
        )
        if not parent:
            raise HTTPException(status_code=404, detail="Parent not found")
        # Replace existing entry for this category
        await conn.execute(
            "DELETE FROM parent_checkins WHERE parent_id = $1::uuid AND category = $2",
            parent_id, category,
        )
        row = await conn.fetchrow(
            """
            INSERT INTO parent_checkins (parent_id, category, time, is_active)
            VALUES ($1::uuid, $2, $3, TRUE)
            RETURNING *
            """,
            parent_id, category, time_str,
        )
    await audit(user["id"], "add_checkin", {"parent_id": parent_id, "category": category, "time": time_str})
    return serialize(row)

@router.delete("/parents/{parent_id}/checkins/all")
async def delete_all_checkins(parent_id: str, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    """Deactivate all check-ins for a parent at once."""
    async with get_pool().acquire() as conn:
        parent = await conn.fetchrow(
            "SELECT * FROM parents WHERE id = $1::uuid AND user_id = $2 AND deleted_at IS NULL",
            parent_id, scope(user),
        )
        if not parent:
            raise HTTPException(status_code=404, detail="Parent not found")
        await conn.execute(
            "UPDATE parent_checkins SET is_active = FALSE WHERE parent_id = $1::uuid",
            parent_id,
        )
    await audit(user["id"], "delete_all_checkins", {"parent_id": parent_id})
    return {"ok": True}

@router.delete("/parents/{parent_id}/checkins/{category}")
async def delete_checkin(parent_id: str, category: str, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    """Soft‑delete a check‑in (set is_active = FALSE)."""
    async with get_pool().acquire() as conn:
        parent = await conn.fetchrow(
            "SELECT * FROM parents WHERE id = $1::uuid AND user_id = $2 AND deleted_at IS NULL",
            parent_id, scope(user),
        )
        if not parent:
            raise HTTPException(status_code=404, detail="Parent not found")
        await conn.execute(
            "UPDATE parent_checkins SET is_active = FALSE WHERE parent_id = $1::uuid AND category = $2",
            parent_id, category,
        )
    await audit(user["id"], "delete_checkin", {"parent_id": parent_id, "category": category})
    return {"ok": True}


# ─── HEALTH REMINDERS ──────────────────────────────────────────────────

HEALTH_CATEGORIES = {"water", "bp_check", "sugar_check", "health_check"}

@router.get("/parents/{parent_id}/health-reminders")
async def list_health_reminders(parent_id: str, user: dict = Depends(get_current_user)):
    async with get_pool().acquire() as conn:
        parent = await conn.fetchrow(
            "SELECT * FROM parents WHERE id = $1::uuid AND user_id = $2 AND deleted_at IS NULL",
            parent_id, scope(user),
        )
        if not parent:
            raise HTTPException(status_code=404, detail="Parent not found")
        rows = await conn.fetch(
            "SELECT * FROM parent_health_reminders WHERE parent_id = $1::uuid AND is_active = TRUE ORDER BY time",
            parent_id,
        )
    return [serialize(r) for r in rows]


@router.post("/parents/{parent_id}/health-reminders")
async def add_health_reminder(parent_id: str, payload: dict, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    category = payload.get("category")
    time_str = payload.get("time")
    if not category or not time_str:
        raise HTTPException(status_code=400, detail="category and time required")
    if category not in HEALTH_CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category. Must be one of: {', '.join(HEALTH_CATEGORIES)}"
        )
    async with get_pool().acquire() as conn:
        parent = await conn.fetchrow(
            "SELECT * FROM parents WHERE id = $1::uuid AND user_id = $2 AND deleted_at IS NULL",
            parent_id, scope(user),
        )
        if not parent:
            raise HTTPException(status_code=404, detail="Parent not found")
        await conn.execute(
            "DELETE FROM parent_health_reminders WHERE parent_id = $1::uuid AND category = $2",
            parent_id, category,
        )
        row = await conn.fetchrow(
            """
            INSERT INTO parent_health_reminders (parent_id, category, time, is_active)
            VALUES ($1::uuid, $2, $3, TRUE)
            RETURNING *
            """,
            parent_id, category, time_str,
        )
    await audit(user["id"], "add_health_reminder", {"parent_id": parent_id, "category": category, "time": time_str})
    return serialize(row)


@router.delete("/parents/{parent_id}/health-reminders/{category}")
async def delete_health_reminder(parent_id: str, category: str, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    async with get_pool().acquire() as conn:
        parent = await conn.fetchrow(
            "SELECT * FROM parents WHERE id = $1::uuid AND user_id = $2 AND deleted_at IS NULL",
            parent_id, scope(user),
        )
        if not parent:
            raise HTTPException(status_code=404, detail="Parent not found")
        await conn.execute(
            "UPDATE parent_health_reminders SET is_active = FALSE WHERE parent_id = $1::uuid AND category = $2",
            parent_id, category,
        )
    await audit(user["id"], "delete_health_reminder", {"parent_id": parent_id, "category": category})
    return {"ok": True}


# ─── ROUTINES ──────────────────────────────────────────────────────────

ROUTINE_CATEGORIES = {"tea_check", "walk_check"}

@router.get("/parents/{parent_id}/routines")
async def list_routines(parent_id: str, user: dict = Depends(get_current_user)):
    async with get_pool().acquire() as conn:
        parent = await conn.fetchrow(
            "SELECT * FROM parents WHERE id = $1::uuid AND user_id = $2 AND deleted_at IS NULL",
            parent_id, scope(user),
        )
        if not parent:
            raise HTTPException(status_code=404, detail="Parent not found")
        rows = await conn.fetch(
            "SELECT * FROM parent_routines WHERE parent_id = $1::uuid AND is_active = TRUE ORDER BY time",
            parent_id,
        )
    return [serialize(r) for r in rows]


@router.post("/parents/{parent_id}/routines")
async def add_routine(parent_id: str, payload: dict, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    category = payload.get("category")
    time_str = payload.get("time")
    if not category or not time_str:
        raise HTTPException(status_code=400, detail="category and time required")
    if category not in ROUTINE_CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category. Must be one of: {', '.join(ROUTINE_CATEGORIES)}"
        )
    async with get_pool().acquire() as conn:
        parent = await conn.fetchrow(
            "SELECT * FROM parents WHERE id = $1::uuid AND user_id = $2 AND deleted_at IS NULL",
            parent_id, scope(user),
        )
        if not parent:
            raise HTTPException(status_code=404, detail="Parent not found")
        await conn.execute(
            "DELETE FROM parent_routines WHERE parent_id = $1::uuid AND category = $2",
            parent_id, category,
        )
        row = await conn.fetchrow(
            """
            INSERT INTO parent_routines (parent_id, category, time, is_active)
            VALUES ($1::uuid, $2, $3, TRUE)
            RETURNING *
            """,
            parent_id, category, time_str,
        )
    await audit(user["id"], "add_routine", {"parent_id": parent_id, "category": category, "time": time_str})
    return serialize(row)

@router.delete("/parents/{parent_id}/routines/{category}")
async def delete_routine(parent_id: str, category: str, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    async with get_pool().acquire() as conn:
        parent = await conn.fetchrow(
            "SELECT * FROM parents WHERE id = $1::uuid AND user_id = $2 AND deleted_at IS NULL",
            parent_id, scope(user),
        )
        if not parent:
            raise HTTPException(status_code=404, detail="Parent not found")
        await conn.execute(
            "UPDATE parent_routines SET is_active = FALSE WHERE parent_id = $1::uuid AND category = $2",
            parent_id, category,
        )
    await audit(user["id"], "delete_routine", {"parent_id": parent_id, "category": category})
    return {"ok": True}


# ─── MEDICINES ──────────────────────────────────────────────────────────

@router.get("/parents/{parent_id}/medicines")
async def list_medicines(parent_id: str, user: dict = Depends(get_current_user)):
    async with get_pool().acquire() as conn:
        parent = await conn.fetchrow(
            "SELECT * FROM parents WHERE id = $1::uuid AND user_id = $2 AND deleted_at IS NULL",
            parent_id, scope(user),
        )
        if not parent:
            raise HTTPException(status_code=404, detail="Parent not found")
        rows = await conn.fetch(
            "SELECT * FROM medicines WHERE parent_id = $1::uuid AND is_active = TRUE ORDER BY created_at",
            parent_id,
        )
    return [serialize(r) for r in rows]

@router.post("/parents/{parent_id}/medicines")
async def add_medicine(parent_id: str, payload: dict, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    name = payload.get("name")
    dosage = payload.get("dosage", "")
    shape = payload.get("shape", "")
    colour = payload.get("colour", "")
    food_timing = payload.get("food_timing", "")
    reminder_times = payload.get("reminder_times", [])
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    async with get_pool().acquire() as conn:
        parent = await conn.fetchrow(
            "SELECT * FROM parents WHERE id = $1::uuid AND user_id = $2 AND deleted_at IS NULL",
            parent_id, scope(user),
        )
        if not parent:
            raise HTTPException(status_code=404, detail="Parent not found")
        row = await conn.fetchrow(
            """
            INSERT INTO medicines (parent_id, name, dosage, shape, colour, food_timing, reminder_times, is_active)
            VALUES ($1::uuid, $2, $3, $4, $5, $6, $7::jsonb, TRUE)
            RETURNING *
            """,
            parent_id, name, dosage, shape, colour, food_timing, json.dumps(reminder_times),
        )
    await audit(user["id"], "add_medicine", {"parent_id": parent_id, "name": name})
    return serialize(row)

@router.delete("/parents/{parent_id}/medicines/all")
async def delete_all_medicines(parent_id: str, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    async with get_pool().acquire() as conn:
        parent = await conn.fetchrow(
            "SELECT * FROM parents WHERE id = $1::uuid AND user_id = $2 AND deleted_at IS NULL",
            parent_id, scope(user),
        )
        if not parent:
            raise HTTPException(status_code=404, detail="Parent not found")
        await conn.execute(
            "UPDATE medicines SET is_active = FALSE WHERE parent_id = $1::uuid",
            parent_id,
        )
    await audit(user["id"], "delete_all_medicines", {"parent_id": parent_id})
    return {"ok": True}


def _local_day_key(dt: datetime, tz_name: str) -> str:
    try:
        tz = ZoneInfo(tz_name or "Asia/Kolkata")
    except Exception:
        tz = ZoneInfo("Asia/Kolkata")
    d = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return d.astimezone(tz).strftime("%Y-%m-%d")


@router.get("/checkins")
async def checkins_summary(
    user: dict = Depends(get_current_user),
    days: int = Query(7, ge=1, le=30),
):
    owner = scope(user)
    pool = get_pool()
    parents = await pool.fetch(
        "select * from parents where user_id = $1 and deleted_at is null limit 50", owner
    )
    if not parents:
        return {"parents": [], "alerts": []}

    parent_ids = [p["id"] for p in parents]
    since = datetime.now(timezone.utc) - timedelta(days=days + 1)

    logs, replies, open_events = await asyncio.gather(
        pool.fetch(
            """
            select * from message_logs
            where parent_id = any($1::uuid[])
              and msg_type = any($2::text[])
              and created_at >= $3
            order by created_at asc
            limit 2000
            """,
            parent_ids, ["checkin", "reminder", "reengagement"], since,
        ),
        pool.fetch(
            """
            select * from parent_replies
            where parent_id = any($1::uuid[]) and created_at >= $2
            order by created_at asc
            limit 2000
            """,
            parent_ids, since,
        ),
        pool.fetch(
            "select * from emergency_events where user_id = $1 and status = 'open' order by created_at desc limit 20",
            owner,
        ),
    )

    replies_by_parent: dict[str, list] = {}
    for r in replies:
        replies_by_parent.setdefault(str(r["parent_id"]), []).append(r)

    # #13 sync: attribute each reply to at most ONE message (consume-once),
    # identical to the monthly report's _daily_details logic — so the Check-ins
    # tab, dashboard stats and the monthly report all report the SAME reply
    # counts (the old logic marked every preceding send 'replied' off one late
    # reply, inflating the dashboard above the report).
    consumed_reply_ids: set = set()

    def _find_reply(parent_id: str, log_dt: datetime, day_key: str, tz_name: str):
        for r in replies_by_parent.get(parent_id, []):
            if str(r["id"]) in consumed_reply_ids:
                continue
            if r["created_at"] < log_dt:
                continue
            if _local_day_key(r["created_at"], tz_name) != day_key:
                continue
            consumed_reply_ids.add(str(r["id"]))
            return r
        return None

    out_parents = []
    for p in parents:
        pid = str(p["id"])
        tz_name = p["timezone"] or "Asia/Kolkata"
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = ZoneInfo("Asia/Kolkata")

        p_logs = [l for l in logs if str(l["parent_id"]) == pid]
        by_day: dict[str, list] = {}
        for l in p_logs:
            dk = _local_day_key(l["created_at"], tz_name)
            by_day.setdefault(dk, []).append(l)

        day_entries = []
        for dk in sorted(by_day.keys(), reverse=True):
            msgs = []
            for l in sorted(by_day[dk], key=lambda x: x["created_at"]):
                reply = _find_reply(pid, l["created_at"], dk, tz_name)
                msgs.append({
                    "id": str(l["id"]),
                    "time": l["created_at"].astimezone(tz).strftime("%H:%M"),
                    "category": l["category"],
                    "msg_type": l["msg_type"],
                    "status": l["status"],
                    "reply_status": l["reply_status"],
                    "replied": reply is not None,
                    "reply": ({
                        "body": reply["transcription"] or reply["body"],
                        "intent": reply["intent"],
                        "is_voice": reply["is_voice"],
                        "created_at": reply["created_at"].isoformat(),
                    } if reply else None),
                })
            replied_count = sum(1 for m in msgs if m["replied"] or m["reply_status"] == "done")
            day_entries.append({
                "day_key": dk,
                "total": len(msgs),
                "replied": replied_count,
                "messages": msgs,
            })

        out_parents.append({
            "parent_id": pid,
            "name": p["name"],
            "days": day_entries[:days],
        })

    alerts = []
    parent_name_by_id = {str(p["id"]): p["name"] for p in parents}
    for e in open_events:
        alerts.append({
            "kind": "emergency",
            "event_id": str(e["id"]),
            "parent_id": str(e["parent_id"]),
            "parent_name": parent_name_by_id.get(str(e["parent_id"]), "Your parent"),
            "body": e["body"],
            "created_at": e["created_at"].isoformat(),
        })
    help_cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    for r in replies:
        if r["intent"] == "reengagement:help" and r["created_at"] >= help_cutoff:
            alerts.append({
                "kind": "reengagement_help",
                "parent_id": str(r["parent_id"]),
                "parent_name": parent_name_by_id.get(str(r["parent_id"]), "Your parent"),
                "body": r["body"],
                "created_at": r["created_at"].isoformat(),
            })

    return {"parents": out_parents, "alerts": alerts}
