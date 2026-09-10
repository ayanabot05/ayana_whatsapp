
"""
monthly_report.py — FIXED: Now generates PDF and sends it on WhatsApp along with template

Fixes your issue:
1. Previously _notify_report_ready only called send_report_ready (text)
2. Now it also generates PDF, uploads to storage, and calls send_report_pdf_with_link + media-id fallback

Requires: reportlab (pip install reportlab)
"""

import logging
import json
from datetime import datetime, timezone, timedelta
from calendar import monthrange
from zoneinfo import ZoneInfo
from io import BytesIO

from database import get_pool
from pricing import plan_limits, PLAN_BY_ID
from whatsapp import send_report_ready, send_report_pdf_with_link, send_document_link
from storage import put_object, signed_url, is_enabled as storage_enabled

logger = logging.getLogger("ayana.monthly_report")

_FEELING_SCORE = {"good": 1.0, "okay": 0.5, "not_well": 0.0}

def _tz(tz_name: str | None):
    try:
        return ZoneInfo(tz_name or "Asia/Kolkata")
    except Exception:
        return ZoneInfo("Asia/Kolkata")

def _local_day(dt: datetime, tz) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz).strftime("%Y-%m-%d")

def _month_bounds(year: int, month: int) -> tuple[str, str]:
    last_day = monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last_day:02d}"

def _day_key_to_dt(day_key: str) -> datetime:
    return datetime.strptime(day_key, "%Y-%m-%d").replace(tzinfo=timezone.utc)

# --- PDF GENERATION ---

def _generate_pdf_bytes(report: dict, details: dict) -> bytes:
    """Generate a simple but clean monthly report PDF"""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import inch
        from reportlab.lib.colors import HexColor
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib import colors
    except ImportError:
        logger.error("[monthly_report] reportlab not installed, cannot generate PDF")
        return None

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, 
                            rightMargin=50, leftMargin=50, topMargin=50, bottomMargin=50)
    styles = getSampleStyleSheet()
    story = []

    # Colors
    primary = HexColor("#8B5CF6")
    
    # Title
    parent_name = details.get("parent_name", report.get("parent_id", "Parent"))
    period = report.get("period", "")
    title = f"<font color='#8B5CF6'><b>AYANA Wellness Report - {parent_name}</b></font><br/><font size=10>{period}</font>"
    story.append(Paragraph(title, styles['Title']))
    story.append(Spacer(1, 0.3*inch))

    # Summary
    story.append(Paragraph(f"<b>Summary</b>", styles['Heading2']))
    summary_data = [
        ["Total Check-ins", str(report.get("total_touches", 0))],
        ["Delivered", str(report.get("delivered", 0))],
        ["Replied", str(report.get("replied", 0))],
        ["Reply Rate", f"{report.get('reply_rate',0)*100:.0f}%"],
        ["Voice Replies", str(report.get("voice_replies", 0))],
        ["Plan", report.get("plan", "")],
    ]
    t = Table(summary_data, colWidths=[2.5*inch, 2.5*inch])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (0,-1), colors.HexColor("#F3F0FF")),
        ('TEXTCOLOR', (0,0), (-1,-1), colors.black),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica'),
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#E5E7EB")),
    ]))
    story.append(t)
    story.append(Spacer(1, 0.3*inch))

    # By Category
    by_category = details.get("by_category", {})
    if by_category:
        story.append(Paragraph(f"<b>By Category</b>", styles['Heading2']))
        cat_data = [["Category", "Sent", "Replied"]]
        for cat, vals in by_category.items():
            cat_data.append([cat, str(vals.get("sent",0)), str(vals.get("replied",0))])
        ct = Table(cat_data, colWidths=[2.5*inch, 1.25*inch, 1.25*inch])
        ct.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), primary),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,-1), 9),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#E5E7EB")),
        ]))
        story.append(ct)
        story.append(Spacer(1, 0.3*inch))

    # Day by day
    days = details.get("days", [])
    if days:
        story.append(Paragraph(f"<b>Day by Day</b>", styles['Heading2']))
        day_data = [["Day", "Sent", "Replied"]]
        for d in sorted(days, key=lambda x: x.get("day",""))[-15:]:  # last 15 days
            day_data.append([d.get("day",""), str(d.get("sent",0)), str(d.get("replied",0))])
        dt = Table(day_data, colWidths=[2*inch, 1.5*inch, 1.5*inch])
        dt.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), primary),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,-1), 8),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#E5E7EB")),
        ]))
        story.append(dt)
        story.append(Spacer(1, 0.3*inch))

    # Trend note
    if report.get("trend_note"):
        story.append(Paragraph(f"<b>Note:</b> {report.get('trend_note')}", styles['Normal']))

    story.append(Spacer(1, 0.5*inch))
    story.append(Paragraph(f"<font size=8 color='#6B7280'>Generated by AYANA on {datetime.now().strftime('%Y-%m-%d %H:%M')} IST | ayana.care</font>", styles['Normal']))

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes

async def _mood_series(conn, parent_id, start_day: str, end_day: str, tz_name: str | None = None) -> list[dict]:
    tz = _tz(tz_name)
    range_start = _day_key_to_dt(start_day)
    range_end = _day_key_to_dt(end_day) + timedelta(days=1)
    replies = await conn.fetch(
        """
        select created_at, intent from parent_replies
        where parent_id = $1 and created_at >= $2 and created_at < $3
          and intent like 'feeling:%'
        order by created_at asc
        """,
        parent_id, range_start, range_end,
    )
    series, seen = [], set()
    for r in replies:
        day = _local_day(r["created_at"], tz)
        if day in seen:
            continue
        seen.add(day)
        feeling = r["intent"].split(":", 1)[1]
        series.append({"day": day, "feeling": feeling, "score": _FEELING_SCORE.get(feeling)})
    return series

async def _daily_details(conn, parent_id, start_day: str, end_day: str, tz_name: str | None = None) -> dict:
    tz = _tz(tz_name)
    range_start = _day_key_to_dt(start_day)
    range_end = _day_key_to_dt(end_day) + timedelta(days=1)

    logs = await conn.fetch(
        """
        select id, day_key, category, msg_type, status, reply_status, created_at, skipped
        from message_logs 
        where parent_id = $1 
          and created_at >= $2 and created_at < $3
          and msg_type = any($4::text[])
        order by created_at asc
        """,
        parent_id, range_start, range_end,
        ["checkin", "reminder", "reengagement"],
    )
    replies = await conn.fetch(
        """
        select id, created_at, intent, is_voice, body from parent_replies
        where parent_id = $1 and created_at >= $2 and created_at < $3
        order by created_at asc
        """,
        parent_id, range_start, range_end,
    )
    emergencies = await conn.fetchval(
        "select count(*) from emergency_events where parent_id = $1 and created_at >= $2 and created_at < $3",
        parent_id, range_start, range_end,
    )

    replies_by_day: dict[str, list] = {}
    for r in replies:
        replies_by_day.setdefault(_local_day(r["created_at"], tz), []).append(r)
    consumed_by_day: dict[str, list] = {dk: [False] * len(rs) for dk, rs in replies_by_day.items()}

    days: dict[str, dict] = {}
    by_category: dict[str, dict] = {}

    for log in logs:
        dk = _local_day(log["created_at"], tz)
        d = days.setdefault(dk, {"day": dk, "sent": 0, "replied": 0, "items": []})
        delivered = log["status"] in ("sent", "simulated")

        replied = False
        day_reps = replies_by_day.get(dk, [])
        flags = consumed_by_day.get(dk, [])
        for i, r in enumerate(day_reps):
            if not flags[i] and r["created_at"] >= log["created_at"]:
                flags[i] = True
                replied = True
                break

        if delivered:
            d["sent"] += 1
        if replied or (log["reply_status"] == "done"):
            d["replied"] += 1
            
        d["items"].append({
            "time": log["created_at"].astimezone(tz).strftime("%H:%M"),
            "category": log["category"],
            "msg_type": log["msg_type"],
            "status": log["status"],
            "reply_status": log["reply_status"],
            "replied": replied or (log["reply_status"] == "done"),
        })
        
        cat = by_category.setdefault(log["category"], {"category": log["category"], "sent": 0, "replied": 0})
        if delivered:
            cat["sent"] += 1
        if replied or (log["reply_status"] == "done"):
            cat["replied"] += 1

    feelings = {"good": 0, "okay": 0, "not_well": 0}
    medicine = {"done": 0, "skipped": 0}
    for r in replies:
        intent = r["intent"] or ""
        if intent.startswith("feeling:"):
            f = intent.split(":", 1)[1]
            if f in feelings:
                feelings[f] += 1
        elif intent.startswith(("done:", "skip:")):
            action, _, cat = intent.partition(":")
            if cat.startswith("medicine"):
                if action == "done":
                    medicine["done"] += 1
                else:
                    medicine["skipped"] += 1

    return {
        "days": sorted(days.values(), key=lambda x: x["day"]),
        "by_category": by_category,
        "feelings": feelings,
        "medicine": medicine,
        "emergencies": emergencies or 0,
        "total_replies": len(replies),
    }

def _trend_note(series: list[dict]) -> str:
    if not series or len(series) < 3:
        return "Mood stayed fairly steady this month."
    scores = [s.get("score", 0.5) for s in series if s.get("score") is not None]
    if not scores:
        return "Mood stayed fairly steady this month."
    avg = sum(scores) / len(scores)
    if avg >= 0.7:
        return "Overall positive mood this month - great to see! 💛"
    elif avg <= 0.3:
        return "Some low mood days noticed - a gentle check-in call might help."
    return "Mood stayed fairly steady this month."

async def _notify_report_ready(conn, user_id: str, parent_id, period: str, shared: bool, pdf_url: str = None, pdf_bytes: bytes = None) -> None:
    """PERMANENT FIX FOR CHILD 24H WINDOW - works even if child never replied"""
    parent = await conn.fetchrow("select * from parents where id = $1", parent_id)
    if not parent:
        return
    parent_display = parent["preferred_name"] or parent["name"] or "Amma"
    language = parent["language"] or "en"

    owner = await conn.fetchrow("select * from users where id = $1::uuid", user_id)
    recipients = [owner] if owner else []
    if shared:
        members = await conn.fetch(
            "select * from users where household_owner_id = $1::uuid and deleted_at is null limit 20",
            user_id,
        )
        recipients += list(members)

    for r in recipients:
        if not r or not r["phone"]:
            continue
        try:
            # PERMANENT SOLUTION: Try template WITH document header first (works outside 24h window)
            # This is for child/siblings who never reply - free-form document fails outside window
            pdf_media_id = None
            if pdf_bytes and not pdf_url:
                # Upload first to get media_id for template header
                try:
                    from whatsapp import upload_media_to_whatsapp
                    pdf_media_id = await upload_media_to_whatsapp(pdf_bytes, f"AYANA-{parent_display}-{period}.pdf")
                except Exception:
                    pdf_media_id = None
            
            if pdf_url or pdf_media_id:
                try:
                    from whatsapp import send_report_ready_with_pdf_template
                    res = await send_report_ready_with_pdf_template(
                        r["phone"], language, parent_display, 
                        pdf_url=pdf_url, pdf_media_id=pdf_media_id, period=period
                    )
                    if res.get("status") == "sent":
                        logger.info("[monthly_report] Report with PDF via TEMPLATE sent to %s (24h window FIXED)", r["phone"])
                        continue  # Success - skip fallback
                except Exception as e:
                    logger.warning("[monthly_report] Template with PDF header failed, fallback to old method: %s", e)
            
            # Fallback: old method (template + separate document) - requires 24h window for document
            res1 = await send_report_ready(r["phone"], language, parent_display)
            logger.info("[monthly_report] report_ready template sent to %s: %s", r["phone"], res1.get("status"))

            if pdf_url or pdf_bytes:
                if pdf_url:
                    from whatsapp import send_report_pdf_with_link
                    res2 = await send_report_pdf_with_link(r["phone"], pdf_url, period, parent_display, language)
                    logger.info("[wa] Document sent to %s via link: %s (requires 24h window)", r["phone"], res2.get("status"))
                    if res2.get("status") == "failed" and pdf_bytes:
                        from whatsapp import upload_media_and_send_document
                        res3 = await upload_media_and_send_document(r["phone"], pdf_bytes, f"AYANA-{parent_display}-{period}.pdf", f"AYANA Report {period}")
                        logger.info("[wa] Document sent to %s via media_id fallback: %s (requires 24h window)", r["phone"], res3.get("status"))
                elif pdf_bytes:
                    from whatsapp import upload_media_and_send_document
                    res2 = await upload_media_and_send_document(r["phone"], pdf_bytes, f"AYANA-{parent_display}-{period}.pdf", f"AYANA Report {period}")
                    logger.info("[wa] Document sent to %s via media_id: %s (requires 24h window)", r["phone"], res2.get("status"))

        except Exception as e:
            logger.error("[monthly_report] report_ready notify failed for user %s: %s", r["id"], e, exc_info=True)

async def generate_monthly_report(user_id: str, parent_id, plan_id: str, year: int, month: int, notify: bool = False) -> dict:
    start_day, end_day = _month_bounds(year, month)
    range_start = _day_key_to_dt(start_day)
    range_end = _day_key_to_dt(end_day) + timedelta(days=1)
    limits = plan_limits(plan_id)

    async with get_pool().acquire() as conn:
        logs = await conn.fetch(
            """
            select * from message_logs 
            where parent_id = $1 
              and created_at >= $2 and created_at < $3
              and msg_type = any($4::text[])
            """,
            parent_id, range_start, range_end,
            ["checkin", "reminder", "reengagement"],
        )

        total = len(logs)
        sent = sum(1 for l in logs if l["status"] in ("sent", "simulated"))
        skipped = sum(1 for l in logs if l["skipped"])

        voice_replies = await conn.fetchval(
            """
            select count(*) from parent_replies
            where parent_id = $1 and is_voice = true and created_at >= $2 and created_at < $3
            """,
            parent_id, range_start, range_end,
        )

        parent_row = await conn.fetchrow("select name, preferred_name, relationship, language, timezone from parents where id = $1", parent_id)
        tz_name = (parent_row["timezone"] if parent_row else None) or "Asia/Kolkata"
        details = await _daily_details(conn, parent_id, start_day, end_day, tz_name)
        details["parent_name"] = (parent_row["name"] if parent_row else None) or "Parent"
        details["relationship"] = parent_row["relationship"] if parent_row else None
        details["plan_name"] = (PLAN_BY_ID.get(plan_id) or {}).get("name", plan_id)

        synced_total = sum(d["sent"] for d in details["days"])
        synced_replied = sum(d["replied"] for d in details["days"])

        report = {
            "user_id": user_id,
            "parent_id": parent_id,
            "plan": plan_id,
            "period": f"{year:04d}-{month:02d}",
            "total_touches": synced_total,
            "delivered": synced_total,
            "skipped": skipped,
            "voice_replies": voice_replies,
            "mood_graph": None,
            "trend_note": None,
            "details": details,
            "shared_with_care_circle": limits.get("family_members", 1) > 1,
            "generated_at": datetime.now(timezone.utc),
            "replied": synced_replied,
            "reply_rate": round(synced_replied / synced_total, 3) if synced_total else 0,
        }

        if limits.get("variants_per_slot", 3) >= 7:
            series = await _mood_series(conn, parent_id, start_day, end_day, tz_name)
            report["mood_graph"] = series
            report["trend_note"] = _trend_note(series)

        # --- GENERATE PDF ---
        pdf_bytes = _generate_pdf_bytes(report, details)
        pdf_url = None

        if pdf_bytes and storage_enabled():
            try:
                # Upload to supabase storage: reports/{user_id}/{parent_id}/{period}.pdf
                key = f"reports/{user_id}/{parent_id}/{report['period']}.pdf"
                put_object(key, pdf_bytes, content_type="application/pdf")
                # Get signed URL valid for 7 days
                pdf_url = signed_url(key, expires_sec=7*24*3600)
                logger.info("[monthly_report] PDF uploaded to %s -> %s", key, pdf_url[:100])
            except Exception as e:
                logger.error("[monthly_report] PDF upload failed: %s", e, exc_info=True)
        elif pdf_bytes:
            logger.warning("[monthly_report] PDF generated but storage disabled, will send via media_id")

        # Save to DB
        await conn.execute(
            """
            insert into monthly_reports
                (user_id, parent_id, plan, period, total_touches, delivered, skipped,
                 voice_replies, mood_graph, trend_note, shared_with_care_circle, generated_at, details, pdf_url)
            values ($1::uuid, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, $11, $12, $13::jsonb, $14)
            on conflict (user_id, parent_id, period) do update
                set plan = excluded.plan,
                    total_touches = excluded.total_touches,
                    delivered = excluded.delivered,
                    skipped = excluded.skipped,
                    voice_replies = excluded.voice_replies,
                    mood_graph = excluded.mood_graph,
                    trend_note = excluded.trend_note,
                    shared_with_care_circle = excluded.shared_with_care_circle,
                    generated_at = excluded.generated_at,
                    details = excluded.details,
                    pdf_url = excluded.pdf_url
            """,
            user_id, parent_id, plan_id, report["period"], report["total_touches"], report["delivered"], skipped,
            voice_replies, json.dumps(report["mood_graph"]) if report["mood_graph"] else None,
            report["trend_note"], report["shared_with_care_circle"], report["generated_at"],
            json.dumps(details), pdf_url,
        )

        # Keep pdf for notifier
        report["_pdf_url"] = pdf_url
        report["_pdf_bytes"] = pdf_bytes

        if notify:
            await _notify_report_ready(conn, user_id, parent_id, report["period"], report["shared_with_care_circle"], pdf_url, pdf_bytes)

    report["generated_at"] = report["generated_at"].isoformat()
    report["parent_id"] = str(parent_id)
    report["user_id"] = str(user_id)
    # Don't return bytes in API response
    report.pop("_pdf_bytes", None)
    report["pdf_url"] = report.pop("_pdf_url", None)
    return report


async def generate_reports_for_month(year: int, month: int):
    async with get_pool().acquire() as conn:
        parents = await conn.fetch("select * from parents where deleted_at is null")

    for parent in parents:
        async with get_pool().acquire() as conn:
            ps = await conn.fetchrow(
                "select * from payment_state where user_id = $1", parent["user_id"]
            )
        plan_id = (ps["plan"] if ps else None) or "nitya"
        try:
            await generate_monthly_report(parent["user_id"], parent["id"], plan_id, year, month, notify=True)
        except Exception as e:
            logger.error("[monthly_report] Failed for parent %s: %s", parent["id"], e, exc_info=True)
