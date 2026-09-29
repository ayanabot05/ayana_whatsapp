#!/usr/bin/env python3
"""
AYANA — flood-gate test & diagnostic.

Run the pure-logic tests (no DB, no network):
    python tests/test_flood_gate.py

Diagnose your REAL data — counts how many times each slot actually fired,
per parent, per day. Any slot that fired more than once in a day, or several
slots firing in the same minute, is the "flood" signature:
    DATABASE_URL="postgres://..." python tests/test_flood_gate.py --db
    # optional: limit to one parent
    DATABASE_URL="..." python tests/test_flood_gate.py --db --parent <parent_uuid>

Tests the anti-flood gating logic used by scheduler._deliver_parent():
  - since = max(created_at, activated_at)
  - slot is skipped if scheduled < since
  - slot is skipped if local - scheduled > MAX_LATE_MINUTES (30)
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scheduler import MAX_LATE_MINUTES  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
A_FULL_DAY = ["08:00", "09:00", "13:00", "17:00", "21:00"]  # breakfast..medicine..night


def _slot_due(now_local, slot_time, since):
    """Replicate the anti-flood gate from scheduler._deliver_parent() lines 64-67."""
    hour, minute = map(int, slot_time.split(':'))
    scheduled = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if since and scheduled < since:
        return False
    if scheduled > now_local:
        return False
    if now_local - scheduled > timedelta(minutes=MAX_LATE_MINUTES):
        return False
    return True


def _eligible_from(created_at, activated_at, tz):
    """Replicate since = max(created_at, activated_at) from scheduler line 62."""
    anchors = [a for a in (created_at, activated_at) if a is not None]
    if not anchors:
        return None
    return max(anchors).astimezone(tz)


def _fire_count(now_local, slots, since):
    """How many of `slots` pass the anti-flood gate at now_local."""
    return [s for s in slots if _slot_due(now_local, s, since)]


def run_logic_tests() -> bool:
    print("=" * 70)
    print("PURE LOGIC TESTS — anti-flood gate (MAX_LATE_MINUTES + since)")
    print("=" * 70)
    ok = True

    def check(label, got, expected):
        nonlocal ok
        status = "PASS" if got == expected else "FAIL"
        if got != expected:
            ok = False
        print(f"  [{status}] {label}\n         got={got}\n         exp={expected}")

    # Scenario A0 — the exact moment of setup (8 PM). NOTHING should fire: no
    # burst of breakfast/lunch/medicine the instant you finish adding a parent.
    setup = datetime(2026, 6, 1, 20, 0, tzinfo=IST)
    since = _eligible_from(
        created_at=datetime(2026, 6, 1, 14, 30, tzinfo=timezone.utc),  # 20:00 IST
        activated_at=datetime(2026, 6, 1, 14, 30, tzinfo=timezone.utc),
        tz=IST,
    )
    check("A0) at 8 PM setup instant → NO check-ins fire (no flood burst)",
          _fire_count(setup, A_FULL_DAY, since), [])

    # Scenario A — later the same evening (9:05 PM). Only the 21:00 slot is due;
    # the earlier slots stay skipped for today because they predate setup.
    now = datetime(2026, 6, 1, 21, 5, tzinfo=IST)
    check("A) 9:05 PM after 8 PM setup → only 21:00 fires (no morning backfill)",
          _fire_count(now, A_FULL_DAY, since), ["21:00"])

    # Scenario B — THE BUG YOU HIT. 2nd parent (Nanna) created TODAY 8 PM, but the
    # ACCOUNT was activated 10 days ago. At 9:05 PM only 21:00 may fire.
    now = datetime(2026, 6, 11, 21, 5, tzinfo=IST)
    since = _eligible_from(
        created_at=datetime(2026, 6, 11, 14, 30, tzinfo=timezone.utc),  # today 20:00 IST
        activated_at=datetime(2026, 6, 1, 3, 0, tzinfo=timezone.utc),   # 10 days ago
        tz=IST,
    )
    fired = _fire_count(now, A_FULL_DAY, since)
    check("B) 2nd parent added 8 PM, account activated 10 days ago → only 21:00",
          fired, ["21:00"])

    # Scenario C — established parent, NEXT morning at 09:05. Only 09:00 is within
    # the 30-minute MAX_LATE_MINUTES window (08:00 is 65 min late, skipped).
    now = datetime(2026, 6, 12, 9, 5, tzinfo=IST)
    since = _eligible_from(
        created_at=datetime(2026, 6, 11, 14, 30, tzinfo=timezone.utc),
        activated_at=datetime(2026, 6, 1, 3, 0, tzinfo=timezone.utc),
        tz=IST,
    )
    fired = _fire_count(now, A_FULL_DAY, since)
    check("C) next morning 09:05 → only 09:00 is within 30min window",
          fired, ["09:00"])

    # Scenario D — established parent at 22:00, all slots are >30min old.
    now = datetime(2026, 6, 12, 22, 0, tzinfo=IST)
    fired = _fire_count(now, A_FULL_DAY, since)
    check("D) 10 PM on a normal day → no slot within 30min window",
          fired, [])

    # Scenario E — no eligibility anchor at all (defensive) → time-only gate.
    now = datetime(2026, 6, 12, 13, 5, tzinfo=IST)
    fired = _fire_count(now, A_FULL_DAY, None)
    check("E) no anchor, 13:05 → only 13:00 is within 30min window",
          fired, ["13:00"])

    print("\nRESULT:", "ALL PASS ✅" if ok else "FAILURES ❌")
    return ok


async def run_db_diagnostic(parent_filter: str | None):
    import asyncpg

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL not set — cannot run --db diagnostic.")
        return
    conn = await asyncpg.connect(dsn)
    try:
        print("=" * 70)
        print("REAL-DATA DIAGNOSTIC — sends per parent / day / slot (last 7 days)")
        print("=" * 70)

        where = "where ml.created_at >= now() - interval '7 days' and ml.status in ('sent','simulated')"
        params = []
        if parent_filter:
            where += " and ml.parent_id = $1"
            params.append(parent_filter)

        rows = await conn.fetch(
            f"""
            select p.name as parent, ml.parent_id, ml.day_key, ml.category,
                   ml.message_index, count(*) as sends,
                   min(ml.created_at) as first_at, max(ml.created_at) as last_at
            from message_logs ml
            join parents p on p.id = ml.parent_id
            {where}
            group by p.name, ml.parent_id, ml.day_key, ml.category, ml.message_index
            order by p.name, ml.day_key, ml.message_index
            """,
            *params,
        )
        if not rows:
            print("No sends found in the last 7 days.")
        floods = 0
        for r in rows:
            flag = ""
            if r["sends"] > 1:
                flag = f"  ⚠️  FLOOD: slot fired {r['sends']}x in one day"
                floods += 1
            print(f"{r['parent']:<12} {r['day_key']}  idx={r['message_index']:<2} "
                  f"{r['category']:<16} sends={r['sends']}  "
                  f"{r['first_at'].strftime('%H:%M')}→{r['last_at'].strftime('%H:%M')}{flag}")

        print("\n--- BURSTS: 3+ sends inside any 5-minute window (the visible flood) ---")
        bursts = await conn.fetch(
            f"""
            with s as (
                select p.name as parent, ml.parent_id,
                       date_trunc('minute', ml.created_at) as minute, count(*) as n
                from message_logs ml join parents p on p.id = ml.parent_id
                {where}
                group by p.name, ml.parent_id, date_trunc('minute', ml.created_at)
            )
            select parent, minute, n from s where n >= 2 order by minute desc limit 40
            """,
            *params,
        )
        if not bursts:
            print("None 🎉  (no minute had 2+ sends)")
        for b in bursts:
            print(f"  {b['parent']:<12} {b['minute']:%Y-%m-%d %H:%M}  →  {b['n']} messages in one minute")

        print(f"\nSUMMARY: {floods} slot(s) fired more than once/day; "
              f"{len(bursts)} minute(s) had multiple sends.")
        print("A healthy system shows 0 flood slots and 0 (or rare) multi-send minutes.")
    finally:
        await conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", action="store_true", help="run the live-data diagnostic (needs DATABASE_URL)")
    ap.add_argument("--parent", help="limit --db diagnostic to one parent uuid")
    args = ap.parse_args()

    passed = run_logic_tests()
    if args.db:
        import asyncio
        print()
        asyncio.run(run_db_diagnostic(args.parent))
    sys.exit(0 if passed else 1)
