
"""
test_single_7032.py — Force send PDF ONLY to +917032538448
Usage: python test_single_7032.py --year 2025 --month 8
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from calendar import monthrange
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.getcwd())

import database as db
from monthly_report import generate_monthly_report, _generate_pdf_bytes, _daily_details
from whatsapp import send_report_ready, upload_media_and_send_document

import logging
logging.basicConfig(level=logging.INFO)

TARGET_PHONE = "+917032538448"

async def main(year, month):
    await db.init_db()
    
    async with db.get_pool().acquire() as conn:
        parent = await conn.fetchrow("""
            SELECT p.* FROM parents p
            JOIN users u ON p.user_id = u.id::uuid
            WHERE u.phone = $1 AND p.deleted_at IS NULL
            LIMIT 1
        """, TARGET_PHONE)
        
        if not parent:
            parent = await conn.fetchrow("SELECT * FROM parents WHERE deleted_at IS NULL LIMIT 1")
        
        if not parent:
            print(f"❌ No parent found")
            return
            
        print(f"✅ Found parent: {parent['name']} ({parent['id']})")

        ps = await conn.fetchrow("SELECT * FROM payment_state WHERE user_id = $1", parent["user_id"])
        plan_id = (ps["plan"] if ps else None) or "nitya"
        print(f"Plan: {plan_id}")

        # Generate details for PDF
        tz_name = parent["timezone"] or "Asia/Kolkata"
        start_day = f"{year:04d}-{month:02d}-01"
        end_day = f"{year:04d}-{month:02d}-{monthrange(year, month)[1]:02d}"
        
        details = await _daily_details(conn, parent["id"], start_day, end_day, tz_name)
        details["parent_name"] = parent["name"]

    # Generate report object
    report = {
        "period": f"{year:04d}-{month:02d}",
        "parent_id": str(parent["id"]),
        "total_touches": sum(d["sent"] for d in details["days"]),
        "delivered": sum(d["sent"] for d in details["days"]),
        "replied": sum(d["replied"] for d in details["days"]),
        "reply_rate": round(sum(d["replied"] for d in details["days"]) / max(1, sum(d["sent"] for d in details["days"])), 3),
        "voice_replies": 0,
        "plan": plan_id,
        "trend_note": f"Monthly report for {parent['name']} - {year}-{month:02d}",
    }

    pdf_bytes = _generate_pdf_bytes(report, details)
    if not pdf_bytes:
        print("❌ PDF generation failed - pip install reportlab")
        return
        
    print(f"✅ PDF generated: {len(pdf_bytes)} bytes")
    
    print(f"\n--- Sending to {TARGET_PHONE} ---")
    res1 = await send_report_ready(TARGET_PHONE, parent["language"] or "en", parent["preferred_name"] or parent["name"])
    print(f"Template: {res1}")
    
    res2 = await upload_media_and_send_document(
        TARGET_PHONE, 
        pdf_bytes, 
        f"AYANA-{parent['name']}-{year}-{month:02d}.pdf",
        f"AYANA Report {year}-{month:02d} for {parent['name']}"
    )
    print(f"PDF: {res2}")
    
    if res2.get("status") == "sent":
        print(f"\n🎉 SUCCESS! PDF delivered to {TARGET_PHONE}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--month", type=int, default=9)
    args = parser.parse_args()
    asyncio.run(main(args.year, args.month))

