"""Reproduce the founder's 'fake data in report' bug and assert the fix.

Scenario (mirrors the screenshots): parent in Asia/Kolkata, 9 sends whose UTC
times are 01:30..04:04 (= 07:00..09:34 IST) on 2026-09-08 plus one at 16:14 UTC
on 2026-09-07 (= 21:44 IST), and only 4 real replies. The report must now:
  - render times in IST (07:00, not 01:30)
  - report an HONEST reply rate (4 replies / 9 sends), not 100%
"""
import asyncio
import os
from datetime import datetime, timezone

import asyncpg

import monthly_report as mr

DSN = os.environ.get("SUPABASE_DB_URL", "postgresql://ayana:ayana@127.0.0.1:5432/ayana")


async def main():
    conn = await asyncpg.connect(DSN)
    try:
        # Fresh user + parent (Asia/Kolkata)
        uid = await conn.fetchval(
            "insert into users (name, email, phone, password_hash, phone_verified) "
            "values ('RepTester', $1, $2, 'x', true) returning id",
            f"rep_{os.urandom(3).hex()}@example.com", f"+9198765{os.urandom(2).hex()[:5]}",
        )
        pid = await conn.fetchval(
            "insert into parents (user_id, name, relationship, phone, language, timezone) "
            "values ($1,'Dady','father',$2,'en','Asia/Kolkata') returning id",
            uid, f"+9199{os.urandom(3).hex()[:7]}0",
        )
        sched_id = await conn.fetchval(
            "insert into schedules (parent_id, user_id, mode, messages, active) "
            "values ($1,$2,'raksha','[]'::jsonb,true) returning id",
            pid, uid,
        )

        def U(h, m, day):  # UTC datetime helper
            return datetime(2026, 9, day, h, m, tzinfo=timezone.utc)

        # (utc_time, day_key_local, category)
        sends = [
            (U(16, 14, 7), "2026-09-07", "goodnight"),
            (U(1, 30, 8), "2026-09-08", "medicine_reminder"),
            (U(2, 4, 8), "2026-09-08", "medicine_reminder"),
            (U(2, 30, 8), "2026-09-08", "morning_hello"),
            (U(2, 34, 8), "2026-09-08", "medicine_reminder"),
            (U(3, 4, 8), "2026-09-08", "medicine_reminder"),
            (U(3, 4, 8), "2026-09-08", "morning_hello"),
            (U(3, 34, 8), "2026-09-08", "morning_hello"),
            (U(4, 4, 8), "2026-09-08", "morning_hello"),
        ]
        for i, (ts, dk, cat) in enumerate(sends):
            await conn.execute(
                "insert into message_logs (user_id, parent_id, schedule_id, message_index, day_key, "
                "category, body, msg_type, status, created_at) "
                "values ($1,$2,$3,$4,$5,$6,'hi','checkin','sent',$7)",
                uid, pid, sched_id, i, dk, cat, ts,
            )
        # Only 4 real replies, all late on 09-08 (after the sends)
        for hh, mm in [(4, 30), (4, 31), (4, 32), (4, 33)]:
            await conn.execute(
                "insert into parent_replies (user_id, parent_id, from_phone, body, intent, is_voice, created_at) "
                "values ($1,$2,'919','ok','feeling:good',false,$3)",
                uid, pid, U(hh, mm, 8),
            )

        details = await mr._daily_details(conn, pid, "2026-09-01", "2026-09-30", "Asia/Kolkata")

        # --- assertions ---
        all_times = [it["time"] for d in details["days"] for it in d["items"]]
        print("times:", sorted(all_times))
        assert "07:00" in all_times, f"expected IST 07:00 in times, got {all_times}"
        assert "01:30" not in all_times, f"UTC time 01:30 leaked into report: {all_times}"

        total_sent = sum(d["sent"] for d in details["days"])
        total_replied = sum(d["replied"] for d in details["days"])
        print(f"sent={total_sent} replied={total_replied} reply_rate={details['reply_rate']} replies_total={details['replies_total']}")
        assert total_sent == 9, f"expected 9 sent, got {total_sent}"
        assert total_replied == 4, f"expected 4 replied (honest), got {total_replied}"
        assert details["reply_rate"] and details["reply_rate"] < 0.9, \
            f"reply_rate should be honest (~0.44), got {details['reply_rate']}"

        # day grouping is local (09-08 has 8, 09-07 has 1)
        by_day = {d["day"]: d for d in details["days"]}
        assert by_day["2026-09-08"]["sent"] == 8, f"09-08 should have 8 sends: {by_day['2026-09-08']}"
        assert by_day["2026-09-07"]["sent"] == 1, f"09-07 should have 1 send: {by_day['2026-09-07']}"

        print("\nALL REPORT ACCURACY CHECKS PASSED")
    finally:
        # cleanup
        await conn.execute("delete from parent_replies where parent_id=$1", pid) if False else None
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
