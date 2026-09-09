"""
test_report_send.py — Test if monthly reports are REALLY sending to child + siblings

Usage:
  1. Set your .env vars (same as server.py)
  2. python test_report_send.py --year 2025 --month 8
  3. Check logs + WhatsApp (or simulated logs)

This calls the SAME function scheduler.py calls on 1st:
  generate_reports_for_month(year, month)
  -> generate_monthly_report(notify=True)
  -> _notify_report_ready() -> sends template + PDF to owner + care circle
"""

import asyncio
import argparse
import os
import sys
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Make sure we can import from your project
sys.path.insert(0, os.getcwd())

from database import get_pool, init_db
from monthly_report import generate_reports_for_month, generate_monthly_report
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("test_report")

async def test_bulk(year, month):
    print(f"\n=== TEST BULK: generate_reports_for_month({year}, {month}) ===")
    print(f"This is EXACTLY what scheduler runs on 1st of month")
    print(f"ENV: AUTO_MONTHLY_REPORTS={os.getenv('AUTO_MONTHLY_REPORTS')} WHATSAPP_ENABLED={os.getenv('WHATSAPP_ENABLED')}")
    print(f"META creds set? token={'YES' if os.getenv('META_WA_ACCESS_TOKEN') else 'NO'} phone_id={'YES' if os.getenv('META_WA_PHONE_NUMBER_ID') else 'NO'}")
    print(f"Storage enabled? {os.getenv('STORAGE_ENABLED') or 'check storage.py'}")
    
    await init_db()
    
    # Show parents that will be processed
    async with get_pool().acquire() as conn:
        parents = await conn.fetch("select id, name, user_id from parents where deleted_at is null limit 20")
        print(f"\nFound {len(parents)} parents (showing max 20):")
        for p in parents:
            # check owner + siblings
            owner = await conn.fetchrow("select id, email, phone from users where id = $1::uuid", p["user_id"])
            members = await conn.fetch("select id, email, phone from users where household_owner_id = $1::uuid and deleted_at is null", p["user_id"])
            print(f"  - Parent: {p['name']} ({p['id']}) Owner: {owner['email'] if owner else 'N/A'} phone={owner['phone'] if owner else 'N/A'} + {len(members)} siblings")
            for m in members:
                print(f"      Sibling: {m['email']} phone={m['phone']}")

    print(f"\n--- Calling generate_reports_for_month({year}, {month}) ---")
    await generate_reports_for_month(year, month)
    print("--- Done ---")

    # Show what was inserted
    async with get_pool().acquire() as conn:
        rows = await conn.fetch("select parent_id, period, total_touches, delivered, shared_with_care_circle, generated_at from monthly_reports where period = $1 order by generated_at desc limit 10", f"{year:04d}-{month:02d}")
        print(f"\nmonthly_reports table for period {year:04d}-{month:02d}: {len(rows)} rows")
        for r in rows:
            print(f"  {r['parent_id']} period={r['period']} delivered={r['delivered']} shared={r['shared_with_care_circle']} at={r['generated_at']}")

    # Show message_logs for report_ready
    async with get_pool().acquire() as conn:
        logs = await conn.fetch("select parent_id, category, status, created_at from message_logs where category='report_ready' order by created_at desc limit 20")
        print(f"\nmessage_logs report_ready last 20: {len(logs)}")
        for l in logs:
            print(f"  {l['created_at']} parent={l['parent_id']} status={l['status']}")

    print("\n=== TEST COMPLETE ===")
    print("Check your server logs for:")
    print("  [monthly_report] PDF uploaded to ...")
    print("  [wa] Template ayana_report_ready ... SIMULATED or sent")
    print("  [wa] Document sent to ...")
    print("\nIf WHATSAPP_ENABLED=false or no creds, you will see SIMULATED - that's expected for local testing.")
    print("To REALLY send WhatsApp, set WHATSAPP_ENABLED=true + META_WA_ACCESS_TOKEN + META_WA_PHONE_NUMBER_ID")

async def test_single(parent_id, year, month):
    print(f"\n=== TEST SINGLE PARENT {parent_id} ===")
    await init_db()
    async with get_pool().acquire() as conn:
        parent = await conn.fetchrow("select * from parents where id = $1", parent_id)
        ps = await conn.fetchrow("select * from payment_state where user_id = $1", parent["user_id"]) if parent else None
    plan_id = (ps["plan"] if ps else None) or "nitya"
    print(f"Parent: {parent['name'] if parent else 'NOT FOUND'} plan={plan_id}")
    from monthly_report import generate_monthly_report
    report = await generate_monthly_report(parent["user_id"], parent["id"], plan_id, year, month, notify=True)
    print(f"Report generated: {report}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=datetime.now().year)
    parser.add_argument("--month", type=int, default=datetime.now().month - 1 if datetime.now().month > 1 else 12)
    parser.add_argument("--parent-id", type=str, default=None)
    args = parser.parse_args()

    if args.parent_id:
        asyncio.run(test_single(args.parent_id, args.year, args.month))
    else:
        asyncio.run(test_bulk(args.year, args.month))
