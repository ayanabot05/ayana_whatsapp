"""Drain scheduled special dates (birthdays, anniversaries, special dates) for parents."""
import logging
from datetime import datetime, timezone
from database import get_pool
from services.schedule_source import local_now, eligible
from whatsapp import send_special_date, whatsapp_enabled

logger = logging.getLogger(__name__)

async def drain():
    if not whatsapp_enabled():
        return
    now = datetime.now(timezone.utc)
    pool = get_pool()
    
    # Query active special dates for non-deleted parents
    async with pool.acquire() as conn:
        records = await conn.fetch("""
            SELECT s.*, p.id as p_id, p.user_id, p.name as parent_name, p.preferred_name, 
                   p.relationship, p.other_parent_name, p.phone, p.language, p.timezone,
                   p.activity_window_start, p.activity_window_end, p.opted_out_at, p.deleted_at
            FROM parent_special_dates s
            JOIN parents p ON s.parent_id = p.id
            WHERE s.active = true AND p.deleted_at IS NULL
        """)
    
    for row in records:
        r = dict(row)
        parent = {
            'id': r['p_id'],
            'user_id': r['user_id'],
            'name': r['parent_name'],
            'preferred_name': r['preferred_name'],
            'relationship': r['relationship'],
            'other_parent_name': r['other_parent_name'],
            'phone': r['phone'],
            'language': r['language'],
            'timezone': r['timezone'],
            'activity_window_start': r['activity_window_start'],
            'activity_window_end': r['activity_window_end'],
            'opted_out_at': r['opted_out_at'],
            'deleted_at': r['deleted_at'],
        }
        
        try:
            local = local_now(parent, now)
        except Exception:
            continue
            
        current_year = local.year
        current_month = local.month
        current_day = local.day
        current_hm = local.strftime('%H:%M')
        
        # Check if date matches and hasn't been sent this year yet
        if r['month'] != current_month or r['day'] != current_day:
            continue
        if r.get('last_sent_year') == current_year:
            continue
            
        target_time = r.get('send_time') or '09:00'
        if current_hm < target_time:
            continue
            
        # Respect quiet hours / eligibility
        if not eligible(parent, local, check_hours=True):
            continue
            
        # Send wish
        async with pool.acquire() as conn, conn.transaction():
            # Advisory lock per special date event
            lock_won = await conn.fetchval(
                "SELECT pg_try_advisory_xact_lock(hashtextextended($1, 0))",
                f"special_date:{r['id']}:{current_year}"
            )
            if not lock_won:
                continue
                
            # Double check inside transaction
            already = await conn.fetchval(
                "SELECT last_sent_year FROM parent_special_dates WHERE id = $1",
                r['id']
            )
            if already == current_year:
                continue
                
            # Fetch user/child name as sender
            user_name = await conn.fetchval("SELECT name FROM users WHERE id = $1", parent['user_id'])
            sender = user_name or "Your family"
            
            try:
                result = await send_special_date(parent, r, sender=sender)
            except Exception as e:
                logger.error(f"Error sending special date {r['id']} for parent {parent['id']}: {e}")
                continue
                
            if result.get('status') in ('sent', 'simulated'):
                await conn.execute("""
                    UPDATE parent_special_dates 
                    SET last_sent_year = $1, last_sent_at = now(), updated_at = now()
                    WHERE id = $2
                """, current_year, r['id'])
                
                # Log message in message_logs
                day_key = local.strftime('%Y-%m-%d')
                body = result.get('body') or f"Special date wish: {r['kind']}"
                await conn.execute("""
                    INSERT INTO message_logs (user_id, parent_id, day_key, category, body, msg_type, status, detail, sid, slot_time, created_at)
                    VALUES ($1, $2, $3, $4, $5, 'special_date', $6, $7, $8, $9, now())
                """, parent['user_id'], parent['id'], day_key, r['kind'], body, result.get('status'), result.get('detail'), result.get('sid'), target_time)
