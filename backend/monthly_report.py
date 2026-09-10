
"""
monthly_report.py — FIXED: NEW Monthly Care Report with REAL AYANA logo emblem
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
def _tz(tz_name):
    try:
        return ZoneInfo(tz_name or "Asia/Kolkata")
    except Exception:
        return ZoneInfo("Asia/Kolkata")
def _local_day(dt, tz):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz).strftime("%Y-%m-%d")
def _month_bounds(year, month):
    last_day = monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last_day:02d}"
def _day_key_to_dt(day_key):
    return datetime.strptime(day_key, "%Y-%m-%d").replace(tzinfo=timezone.utc)

"""
monthly_report.py — FIXED: NEW Monthly Care Report with REAL AYANA logo emblem
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
def _tz(tz_name):
    try:
        return ZoneInfo(tz_name or "Asia/Kolkata")
    except Exception:
        return ZoneInfo("Asia/Kolkata")
def _local_day(dt, tz):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz).strftime("%Y-%m-%d")
def _month_bounds(year, month):
    last_day = monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last_day:02d}"
def _day_key_to_dt(day_key):
    return datetime.strptime(day_key, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _generate_pdf_bytes(report, details):
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        from reportlab.lib.colors import HexColor, Color
        from reportlab.lib.utils import ImageReader
        import os
    except ImportError:
        logger.error("[monthly_report] reportlab not installed")
        return None
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    page_w, page_h = A4
    margin_x = 14 * 2.83465
    content_w = page_w - margin_x*2
    primary = Color(15/255, 61/255, 46/255)
    primary_soft = Color(232/255, 242/255, 236/255)
    border_col = Color(239/255, 232/255, 216/255)
    row_alt = Color(250/255, 246/255, 236/255)
    muted = Color(154/255, 145/255, 131/255)
    text_col = Color(26/255, 26/255, 26/255)
    dot_replied = Color(16/255, 150/255, 72/255)
    dot_pending = Color(206/255, 199/255, 181/255)
    pill_idle = Color(244/255, 244/255, 241/255)
    parent_name = details.get("parent_name", report.get("parent_id", "Parent"))
    period = report.get("period", "")
    try:
        y_, m_ = period.split("-")
        month_label = datetime(int(y_), int(m_), 1).strftime("%B %Y")
    except:
        month_label = period
    days = details.get("days", [])
    total_sent = sum(d.get("sent",0) for d in days) or report.get("total_touches",0) or report.get("delivered",0)
    total_replied = sum(d.get("replied",0) for d in days) or report.get("replied",0)
    completion = round((total_replied/total_sent*100) if total_sent else 0)
    skipped = report.get("skipped",0) or 0
    voice = report.get("voice_replies",0) or 0
    feelings = details.get("feelings", {})
    medicine = details.get("medicine", {})
    emergencies = details.get("emergencies",0)
    by_category = details.get("by_category", {})
    def draw_tracked(txt, x, y_pos, size=7.5, spacing=0.7):
        c.setFont("Helvetica", size)
        cx = x
        for ch in txt:
            c.drawString(cx, y_pos, ch)
            cx += c.stringWidth(ch, "Helvetica", size) + spacing
    def draw_footer():
        c.setStrokeColor(border_col)
        c.setLineWidth(0.5)
        c.line(margin_x, 14*2.83465, page_w-margin_x, 14*2.83465)
        c.setFont("Helvetica", 7)
        c.setFillColor(muted)
        c.drawString(margin_x, 9*2.83465, "AYANA is not an emergency or medical service. This report summarises WhatsApp check-in activity only.")
        c.drawRightString(page_w-margin_x, 9*2.83465, "ayana.care")
    def ensure_space(needed):
        nonlocal y
        if y - needed < 18*2.83465:
            draw_footer()
            c.showPage()
            y = page_h - 16*2.83465
            try:
                logo_path = "/mnt/data/ayana_emblem_400.png"
                if os.path.exists(logo_path):
                    c.saveState()
                    c.setFillAlpha(0.05)
                    c.drawImage(ImageReader(logo_path), page_w/2 - 30*2.83465, page_h/2 - 30*2.83465, 60*2.83465, 60*2.83465, preserveAspectRatio=True, mask='auto')
                    c.restoreState()
            except:
                pass
    y = page_h - 16*2.83465
    try:
        logo_path = "/mnt/data/ayana_emblem_400.png"
        if os.path.exists(logo_path):
            c.saveState()
            c.setFillAlpha(0.05)
            c.drawImage(ImageReader(logo_path), page_w/2 - 30*2.83465, page_h/2 - 30*2.83465, 60*2.83465, 60*2.83465, preserveAspectRatio=True, mask='auto')
            c.restoreState()
    except:
        pass
    try:
        logo_path = "/mnt/data/ayana_emblem_400.png"
        if os.path.exists(logo_path):
            c.drawImage(ImageReader(logo_path), margin_x, y-10*2.83465, 10*2.83465, 10*2.83465, preserveAspectRatio=True, mask='auto')
        else:
            c.setFillColor(primary)
            c.roundRect(margin_x, y-10*2.83465, 10*2.83465, 10*2.83465, 2*2.83465, fill=1, stroke=0)
            c.setFillColor(HexColor("#FFFFFF"))
            c.setFont("Times-Bold", 9)
            c.drawCentredString(margin_x+5*2.83465, y-4*2.83465, "A")
    except:
        c.setFillColor(primary)
        c.roundRect(margin_x, y-10*2.83465, 10*2.83465, 10*2.83465, 2*2.83465, fill=1, stroke=0)
        c.setFillColor(HexColor("#FFFFFF"))
        c.setFont("Times-Bold", 9)
        c.drawCentredString(margin_x+5*2.83465, y-4*2.83465, "A")
    c.setFillColor(muted)
    c.setFont("Helvetica", 7.5)
    draw_tracked("MONTHLY CARE REPORT", margin_x+14*2.83465, y-2*2.83465, 7.5, 0.7)
    c.setFillColor(text_col)
    c.setFont("Times-Bold", 18)
    c.drawString(margin_x+14*2.83465, y-8*2.83465, f"{parent_name} · {month_label}")
    c.setFont("Helvetica", 8.5)
    c.setFillColor(muted)
    now_str = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%m/%d/%Y, %I:%M:%S %p")
    c.drawRightString(page_w-margin_x, y-2*2.83465, f"Generated {now_str}")
    c.setFont("Times-Bold", 11)
    c.setFillColor(primary)
    c.drawRightString(page_w-margin_x, y-7*2.83465, "AYANA")
    y -= 18*2.83465
    c.setStrokeColor(border_col)
    c.setLineWidth(0.5)
    c.line(margin_x, y, page_w-margin_x, y)
    y -= 8*2.83465
    strongest = ""
    if by_category:
        best = max(by_category.items(), key=lambda kv: (kv[1].get("replied",0)/kv[1].get("sent",1)) if kv[1].get("sent") else 0, default=None)
        if best and best[1].get("sent",0)>0:
            rate = best[1].get("replied",0)/best[1].get("sent",1)*100
            if rate>=90:
                strongest = f" — strongest with {best[0].replace('_', ' ')} ({rate:.0f}%)."
    c.setFont("Helvetica", 9)
    c.setFillColor(text_col)
    summary_text = f"{parent_name} completed {completion}% of check-ins this month across {len(by_category)} message types{strongest}"
    c.drawString(margin_x, y, summary_text[:115])
    y -= 10*2.83465
    card_gap = 4*2.83465
    card_w = (content_w - card_gap*3)/4
    card_h = 22*2.83465
    def draw_stat_card(x, value, label, sub=None):
        c.setFillColor(HexColor("#FFFFFF"))
        c.setStrokeColor(border_col)
        c.roundRect(x, y-card_h, card_w, card_h, 2*2.83465, fill=1, stroke=1)
        c.setFont("Times-Bold", 16)
        c.setFillColor(text_col)
        c.drawString(x+4*2.83465, y-7*2.83465, str(value))
        c.setFont("Helvetica", 8.5)
        c.setFillColor(muted)
        c.drawString(x+4*2.83465, y-11*2.83465, label)
        if sub:
            c.setFont("Helvetica", 7.5)
            c.drawString(x+4*2.83465, y-15*2.83465, sub)
    draw_stat_card(margin_x, total_sent, "Messages sent", month_label)
    draw_stat_card(margin_x+card_w+card_gap, f"{completion}%", "Completion rate", f"{total_replied} completed")
    draw_stat_card(margin_x+(card_w+card_gap)*2, skipped, "Skipped", None)
    draw_stat_card(margin_x+(card_w+card_gap)*3, voice, "Voice notes", None)
    y -= card_h + 6*2.83465
    row2_w = (content_w - card_gap*2)/3
    row2_h = 20*2.83465
    def draw_info_card(x, title, body):
        c.setStrokeColor(border_col)
        c.setFillColor(HexColor("#FFFFFF"))
        c.roundRect(x, y-row2_h, row2_w, row2_h, 2*2.83465, fill=1, stroke=1)
        c.setFont("Helvetica-Bold", 8.5)
        c.setFillColor(text_col)
        c.drawString(x+4*2.83465, y-6*2.83465, title)
        c.setFont("Helvetica", 8)
        c.setFillColor(muted)
        c.drawString(x+4*2.83465, y-11*2.83465, body[:46])
        if len(body)>46:
            c.drawString(x+4*2.83465, y-14*2.83465, body[46:92])
    feelings_line = "No feelings recorded yet"
    if feelings and sum(feelings.values())>0:
        feelings_line = "  ".join([f"{k.replace('_', ' ')} x{v}" for k,v in feelings.items() if v>0])
    medicine_line = f"Taken {medicine.get('done',0)}   Skipped {medicine.get('skipped',0)}"
    alerts_line = f"{emergencies} alerts" if emergencies else "No alerts this month"
    draw_info_card(margin_x, "How they responded", feelings_line)
    draw_info_card(margin_x+row2_w+card_gap, "Medicine", medicine_line)
    draw_info_card(margin_x+(row2_w+card_gap)*2, "Attention alerts", alerts_line)
    y -= row2_h + 10*2.83465
    ensure_space(16*2.83465)
    c.setFont("Times-Bold", 13)
    c.setFillColor(text_col)
    c.drawString(margin_x, y, f"Message Breakdown — {parent_name}")
    y -= 6*2.83465
    c.setFillColor(primary_soft)
    c.rect(margin_x, y-7*2.83465, content_w, 7*2.83465, fill=1, stroke=0)
    c.setFont("Helvetica", 8.5)
    c.setFillColor(muted)
    c.drawString(margin_x+3*2.83465, y-4.5*2.83465, "Message")
    c.drawRightString(margin_x+content_w-14*2.83465, y-4.5*2.83465, "Sent")
    c.drawRightString(margin_x+content_w-3*2.83465, y-4.5*2.83465, "Replied")
    y -= 7*2.83465
    for i, (cat, vals) in enumerate(by_category.items()):
        ensure_space(8*2.83465)
        if i%2==1:
            c.setFillColor(row_alt)
            c.rect(margin_x, y-7*2.83465, content_w, 7*2.83465, fill=1, stroke=0)
        c.setFillColor(text_col)
        c.setFont("Helvetica", 9)
        c.drawString(margin_x+3*2.83465, y-4.5*2.83465, cat.replace("_"," "))
        c.drawRightString(margin_x+content_w-14*2.83465, y-4.5*2.83465, str(vals.get("sent",0)))
        c.drawRightString(margin_x+content_w-3*2.83465, y-4.5*2.83465, str(vals.get("replied",0)))
        c.setStrokeColor(border_col)
        c.line(margin_x, y-7*2.83465, margin_x+content_w, y-7*2.83465)
        y -= 7*2.83465
    y -= 6*2.83465
    ensure_space(16*2.83465)
    c.setFont("Times-Bold", 13)
    c.setFillColor(text_col)
    c.drawString(margin_x, y, f"Daily Activity — {parent_name}")
    y -= 8*2.83465
    for d in sorted(days, key=lambda x: x.get("day",""), reverse=True)[:20]:
        ensure_space(12*2.83465)
        day_str = d.get("day","")[5:]
        replied = d.get("replied",0)
        sent = d.get("sent",0)
        c.setFont("Helvetica", 8.5)
        c.setFillColor(muted)
        c.drawString(margin_x, y-2*2.83465, day_str)
        c.setFillColor(text_col)
        c.drawRightString(margin_x+content_w, y-2*2.83465, f"{replied}/{sent} replied")
        px = margin_x + 30*2.83465
        pill_y = y
        items = d.get("items", []) or []
        for m in items[:6]:
            replied_flag = m.get("replied") or m.get("reply_status")=="done"
            label = f"{m.get('time','')} {m.get('category','').replace('_',' ')}".strip()
            c.setFont("Helvetica", 7)
            text_w = c.stringWidth(label, "Helvetica", 7)
            w = text_w + 10*2.83465
            if px + w > margin_x+content_w-5*2.83465:
                px = margin_x + 30*2.83465
                pill_y -= 6*2.83465
                ensure_space(10*2.83465)
            c.setFillColor(primary_soft if replied_flag else pill_idle)
            c.roundRect(px, pill_y-5.5*2.83465, w, 5.5*2.83465, 2*2.83465, fill=1, stroke=0)
            c.setFillColor(dot_replied if replied_flag else dot_pending)
            c.circle(px+3.4*2.83465, pill_y-2.6*2.83465, 1*2.83465, fill=1, stroke=0)
            c.setFillColor(primary if replied_flag else muted)
            c.drawString(px+6.2*2.83465, pill_y-2*2.83465, label)
            px += w + 2*2.83465
        y = pill_y - 9*2.83465
    draw_footer()
    c.showPage()
    c.save()
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


async def _mood_series(conn, parent_id, start_day: str, end_day: str, tz_name: str = None) -> list:
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

async def _daily_details(conn, parent_id, start_day: str, end_day: str, tz_name: str = None) -> dict:
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

    days: dict = {}
    by_category: dict = {}

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

def _trend_note(series: list) -> str:
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

