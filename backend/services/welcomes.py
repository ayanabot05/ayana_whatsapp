"""Durable welcomes. A unique row is atomically claimed before submission."""

import json
import logging
from datetime import datetime, timezone, timedelta

from database import get_pool
from whatsapp import _send_content_template_with_retry, whatsapp_enabled
from services.notification_transport import post_meta

logger = logging.getLogger("ayana")

RETRYABLE = {130429, 131000, 131016, 131056}

# Meta rejected the TEMPLATE itself (missing / wrong language / param mismatch /
# paused / disabled). Nothing was sent, so these are safe to retry once the
# template is fixed on Meta's side. They go to 'configuration_error', which
# recover_template_configuration() re-queues every ~15 minutes automatically.
TEMPLATE_CONFIG_ERRORS = {132000, 132001, 132012, 132015, 132016}


def _safe_lang(value):
    return value if value in ("en", "te", "hi") else "en"


async def enqueue(conn, key, phone, payload, recipient_id=None, kind=None, version=0):
    await conn.execute(
        """INSERT INTO welcome_deliveries(
               event_key, phone, payload, recipient_id, recipient_kind, contact_version
           )
           VALUES($1,$2,$3::jsonb,$4,$5,$6)
           ON CONFLICT(event_key) DO UPDATE
           SET phone = EXCLUDED.phone,
               payload = EXCLUDED.payload,
               status = CASE
                   WHEN welcome_deliveries.status IN ('failed', 'configuration_error', 'awaiting_consent', 'awaiting_verification', 'awaiting_inbound', 'disabled')
                   THEN 'pending'
                   ELSE welcome_deliveries.status
               END,
               attempts = CASE
                   WHEN welcome_deliveries.status IN ('failed', 'configuration_error', 'awaiting_consent', 'awaiting_verification', 'awaiting_inbound', 'disabled')
                   THEN 0
                   ELSE welcome_deliveries.attempts
               END,
               next_attempt_at = CASE
                   WHEN welcome_deliveries.status IN ('failed', 'configuration_error', 'awaiting_consent', 'awaiting_verification', 'awaiting_inbound', 'disabled')
                   THEN now()
                   ELSE welcome_deliveries.next_attempt_at
               END,
               updated_at = now()""",
        key,
        phone,
        json.dumps(payload),
        recipient_id,
        kind,
        version,
    )


async def queue_child(owner, checking_for=None, *, conn=None):
    """
    Queue the child/owner welcome.

    Uses ayana_child_welcome_<lang>, with {{1}} = child first name.
    Existing consent, verification and once-per-contact gates still apply.
    """
    if not owner.get("email_verified_at"):
        logger.warning(
            "[welcome] queue_child skipped for user %s — email_verified_at is missing",
            owner.get("id"),
        )
        return

    conn = conn or get_pool()
    version = owner.get("contact_version", 0)
    key = (
        f"child:{owner['id']}:email-verified"
        + (f":contact:{version}" if version else "")
    )

    await enqueue(
        conn,
        key,
        owner["phone"],
        {
            "name": (owner.get("name") or "there").split()[0],
            "checking_for": checking_for or "your parent",
            "language": _safe_lang(owner.get("language")),
            "purpose": "child",
        },
        owner["id"],
        "user",
        version,
    )
    return key


async def queue_sibling(sibling, checking_for, conn=None):
    """Durable counterpart to the old best-effort send_sibling_welcome()."""
    conn = conn or get_pool()
    version = sibling.get("contact_version", 0)
    key = f"sibling:{sibling['id']}" + (
        f":contact:{version}" if version else ""
    )
    await enqueue(
        conn,
        key,
        sibling["phone"],
        {
            "name": (sibling.get("name") or "there").split()[0],
            "checking_for": checking_for,
            "language": _safe_lang(sibling.get("language")),
            "purpose": "sibling",
        },
        sibling["id"],
        "sibling",
        sibling.get("contact_version", 0),
    )
    return key


async def welcome_sibling(sibling, checking_for):
    """Enqueue + immediately attempt delivery."""
    key = await queue_sibling(sibling, checking_for)
    return await deliver(key)


async def cancel_recipient(conn, kind, recipient_id):
    """Cancel any not-yet-delivered welcome for a removed recipient."""
    await conn.execute(
        """UPDATE welcome_deliveries
           SET status='cancelled', updated_at=now()
           WHERE recipient_kind=$1
             AND recipient_id=$2
             AND status IN ('pending','retry','disabled','awaiting_consent')""",
        kind,
        recipient_id,
    )


async def send_once(key, phone, name, checking_for, language):
    await enqueue(
        get_pool(),
        key,
        phone,
        {
            "name": name,
            "checking_for": checking_for,
            "language": _safe_lang(language),
            "purpose": "parent",
        },
    )
    return await deliver(key)


async def deliver(key):
    if not whatsapp_enabled():
        return {"status": "disabled"}

    job = await get_pool().fetchrow(
        """UPDATE welcome_deliveries
           SET status='sending',
               attempts=attempts+1,
               updated_at=now()
           WHERE event_key=$1
             AND status IN ('pending','retry','disabled','awaiting_consent','awaiting_verification','configuration_error')
             AND next_attempt_at<=now()
             AND attempts<8
           RETURNING *""",
        key,
    )

    if not job:
        existing = await get_pool().fetchrow(
            "SELECT * FROM welcome_deliveries WHERE event_key=$1", key
        )
        return dict(existing) if existing else {"status": "missing"}

    try:
        payload = (
            json.loads(job["payload"])
            if isinstance(job["payload"], str)
            else job["payload"]
        )

        if not payload:
            await get_pool().execute(
                """UPDATE welcome_deliveries
                   SET status='needs_review',
                       detail='Legacy welcome has no recoverable payload.'
                   WHERE event_key=$1""",
                key,
            )
            return {"status": "needs_review"}

        async with get_pool().acquire() as conn, conn.transaction():
            phone = job["phone"]
            recipient = None

            if job["recipient_id"]:
                await conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
                    "recipient:" + str(job["recipient_id"]),
                )

                table = {
                    "user": "users",
                    "sibling": "care_circle_siblings",
                    "parent": "parents",
                }[job["recipient_kind"]]

                recipient = await conn.fetchrow(
                    f"SELECT * FROM {table} WHERE id=$1", job["recipient_id"]
                )

                if (
                    not recipient
                    or dict(recipient).get("deleted_at")
                    or dict(recipient).get("opted_out_at")
                ):
                    await conn.execute(
                        "UPDATE welcome_deliveries SET status='cancelled' WHERE event_key=$1",
                        key,
                    )
                    return {"status": "cancelled"}

                phone = recipient["phone"]

                if job["recipient_kind"] in ("user", "sibling"):
                    from services.family_access import recipient as eligible_recipient
                    owner_id = (
                        (dict(recipient).get("household_owner_id") or recipient["id"])
                        if job["recipient_kind"] == "user"
                        else recipient["owner_id"]
                    )
                    if not await eligible_recipient(
                        conn, owner_id, job["recipient_kind"], recipient["id"]
                    ):
                        await conn.execute(
                            "UPDATE welcome_deliveries SET status='cancelled' WHERE event_key=$1",
                            key,
                        )
                        return {"status": "cancelled"}

                if payload["purpose"] == "child":
                    if not recipient.get("email_verified_at"):
                        await conn.execute(
                            """UPDATE welcome_deliveries
                               SET status='awaiting_verification',
                                   attempts=greatest(attempts-1,0),
                                   next_attempt_at=now()+interval '5 minutes'
                               WHERE event_key=$1""",
                            key,
                        )
                        return {"status": "awaiting_verification"}

            language = _safe_lang(payload["language"])
            if job["recipient_kind"] in ("user", "sibling"):
                from services.family_access import recipient_language
                language = recipient_language(dict(recipient))

            from services.notifications import window_open

            opened = (
                await window_open(
                    conn,
                    phone,
                    dict(recipient).get("phone_changed_at"),
                )
                if job["recipient_id"] and recipient
                else False
            )

            template_name = None

            if payload["purpose"] == "child":
                template_name = f"ayana_child_welcome_{language}"
                result = await _send_content_template_with_retry(
                    phone,
                    template_name,
                    language,
                    {"1": payload["name"]},
                    "child_welcome",
                )
                # If ayana_child_welcome is pending approval on Meta:
                # For Indian numbers (+91), fallback to opener works.
                # For international numbers (+1, etc.), Meta blocks cold MARKETING templates with 131049.
                # So keep international numbers in retry status until the approved UTILITY template is active.
                if result.get("status") in ("failed", "configuration_error") and (
                    result.get("error_code") in (132000, 132001)
                    or "not exist" in str(result.get("detail", "")).lower()
                ):
                    is_india = phone.startswith("+91") or phone.startswith("91")
                    if is_india:
                        logger.info("[welcome] child_welcome_%s not approved on Meta yet, falling back to opener template for domestic number", language)
                        template_name = f"ayana_opener_{language}"
                        result = await _send_content_template_with_retry(
                            phone,
                            template_name,
                            language,
                            {
                                "1": payload["name"],
                                "2": payload.get("checking_for") or "your parents",
                            },
                            "child_welcome",
                        )
                    else:
                        logger.info(
                            "[welcome] child_welcome_%s pending Meta review. Awaiting UTILITY approval for international number %s to prevent 131049 ecosystem drop.",
                            language, phone
                        )
                        result = {
                            "status": "retry",
                            "error_code": 132001,
                            "detail": f"Awaiting Meta approval for UTILITY template {template_name}. Automatic retry scheduled.",
                        }

            elif payload["purpose"] == "sibling" and opened:
                body = (
                    f"Hi {payload['name']}! You are connected to "
                    f"{payload['checking_for']}'s AYANA care updates."
                )
                result = await post_meta(
                    {
                        "messaging_product": "whatsapp",
                        "to": phone,
                        "type": "text",
                        "text": {"body": body},
                    }
                )

            else:
                # Parent and sibling-outside-window use the same opener template.
                template_name = f"ayana_opener_{language}"
                result = await _send_content_template_with_retry(
                    phone,
                    template_name,
                    language,
                    {
                        "1": payload["name"],
                        "2": payload["checking_for"],
                    },
                    "opener",
                )

            error_code = result.get("error_code")
            detail = result.get("detail")

            state = (
                "accepted"
                if result.get("status") == "sent"
                else result.get("status", "failed")
            )

            if state == "failed" and error_code in TEMPLATE_CONFIG_ERRORS:
                # Template missing/unapproved/mismatched on Meta. Nothing was
                # delivered; surface a clear reason and let the 15-minute
                # configuration recovery retry once it is fixed.
                state = "configuration_error"
                detail = (
                    f"Meta rejected template '{template_name}' "
                    f"(lang '{language}', code {error_code}). "
                    "Create/approve it in WhatsApp Manager under the same "
                    "WABA as this phone number; delivery retries automatically."
                )
                logger.error("[welcome] %s key=%s", detail, key)
            elif (
                state == "failed"
                and (not error_code or error_code in RETRYABLE)
                and job["attempts"] < 8
            ):
                state = "retry"
            elif error_code in (131049, 131047):
                if job.get("recipient_kind") in ("user", "sibling") or payload.get("purpose") == "child":
                    state = "retry"
                else:
                    state = "awaiting_inbound"
            elif job["attempts"] < 8:
                state = "retry"

            await conn.execute(
                """UPDATE welcome_deliveries
                   SET phone=$2,
                       status=$3,
                       sid=$4,
                       detail=$5,
                       next_attempt_at=now()+interval '5 minutes',
                       updated_at=now()
                   WHERE event_key=$1""",
                key,
                phone,
                state,
                result.get("sid"),
                detail,
            )
            return {"status": state, "detail": detail}

    except Exception:
        # Previously silent: any failure here became 'uncertain' with no trace.
        logger.exception("[welcome] deliver failed for %s", key)
        await get_pool().execute(
            """UPDATE welcome_deliveries
               SET status='uncertain',
                   detail='Submission interrupted; reconcile before retrying.',
                   updated_at=now()
               WHERE event_key=$1""",
            key,
        )
        return {"status": "uncertain"}


async def drain():
    if not whatsapp_enabled():
        return
    await recover_missing_child_welcomes()
    await recover_stuck_deliveries()
    await recover_template_configuration()

    await get_pool().execute(
        """UPDATE welcome_deliveries
           SET status='uncertain',
               detail='Interrupted welcome submission.',
               updated_at=now()
           WHERE status='sending'
             AND updated_at<now()-interval '5 minutes'"""
    )

    rows = await get_pool().fetch(
        """SELECT event_key
           FROM welcome_deliveries
           WHERE status IN ('pending','retry','disabled','awaiting_consent','awaiting_verification','configuration_error','failed')
             AND next_attempt_at<=now()
             AND attempts<8
           ORDER BY next_attempt_at
           LIMIT 20"""
    )

    for row in rows:
        await deliver(row["event_key"])


async def recover_missing_child_welcomes():
    """Repair missing jobs after a failed onboarding transaction, once per contact.

    Accepted and uncertain jobs are deliberately retained, never replayed.
    Verification and the latest explicit child consent are both required.
    """
    pool = get_pool()
    owners = await pool.fetch("""SELECT u.* FROM users u
        WHERE u.deleted_at IS NULL AND u.email_verified_at IS NOT NULL
          AND (SELECT c.agreed FROM consent_logs c WHERE c.user_id=u.id
               AND c.consent_type='child' ORDER BY c.created_at DESC LIMIT 1)=true
          AND NOT EXISTS(SELECT 1 FROM welcome_deliveries w
              WHERE w.recipient_id=u.id AND w.recipient_kind='user'
                AND w.contact_version=u.contact_version)
        ORDER BY u.created_at LIMIT 20""")
    for raw in owners:
        owner = dict(raw)
        parent_name = await pool.fetchval("""SELECT coalesce(nullif(preferred_name,''),name)
            FROM parents WHERE user_id=$1 AND deleted_at IS NULL ORDER BY created_at LIMIT 1""", owner['id'])
        await queue_child(owner, parent_name)


async def recover_template_configuration():
    """Retry only definitely unsubmitted welcomes after the required approval exists."""
    from services.template_registry import build
    pool = get_pool()
    for job in await pool.fetch("SELECT * FROM welcome_deliveries WHERE status='configuration_error' AND next_attempt_at<=now() ORDER BY next_attempt_at LIMIT 100"):
        payload = json.loads(job['payload']) if isinstance(job['payload'], str) else job['payload']
        if not payload:
            continue
        language = _safe_lang(payload.get('language'))
        kind = 'child_welcome' if payload.get('purpose') == 'child' else 'opener'
        values = [payload.get('name') or 'there']
        if kind == 'opener':
            values.append(payload.get('checking_for') or 'your family')
        try:
            build(f'ayana_{kind}_{language}', language, values)
        except ValueError:
            await pool.execute("UPDATE welcome_deliveries SET next_attempt_at=now()+interval '5 minutes' WHERE event_key=$1 AND status='configuration_error'", job['event_key'])
            continue
        await pool.execute("UPDATE welcome_deliveries SET status='retry',attempts=0,next_attempt_at=now(),detail=NULL WHERE event_key=$1 AND status='configuration_error'", job['event_key'])


async def inbound_recovery(phone, stamp):
    if stamp < datetime.now(timezone.utc) - timedelta(hours=24):
        return

    # A genuine inbound permits free-form welcome recovery, not Marketing bypass.
    await get_pool().execute(
        """UPDATE welcome_deliveries
           SET status='retry', attempts=0, next_attempt_at=now()
           WHERE phone=$1
             AND recipient_kind IN ('user','sibling')
             AND status IN ('awaiting_inbound','failed','disabled')""",
        phone,
    )

    await get_pool().execute(
        "UPDATE users SET needs_inbound_click=false WHERE phone=$1", phone
    )

    # Issue #0 fix: also recover reply notifications blocked by Meta ecosystem
    # policy (131049) or session-window issues (131047 → 'awaiting_template').
    # Without this, the son's reply notifications stay stuck even after they
    # message the bot and open the 24h window.
    await get_pool().execute(
        """UPDATE reply_notifications
           SET status='pending', attempts=0, next_attempt_at=now(),
               detail=NULL, sid=NULL
           WHERE to_phone=$1
             AND status IN ('blocked_policy', 'awaiting_template', 'failed', 'disabled')
             AND created_at > now() - interval '24 hours'""",
        phone,
    )


async def recover_stuck_deliveries():
    """Recover welcome/notification deliveries where the recipient's phone changed."""
    pool = get_pool()

    await pool.execute(
        """
        UPDATE welcome_deliveries w
        SET phone=r.phone, status='retry', attempts=0, next_attempt_at=now()
        FROM users r
        WHERE w.recipient_kind='user'
          AND w.recipient_id=r.id
          AND w.phone <> r.phone
          AND r.deleted_at IS NULL
          AND w.status IN ('failed','disabled','awaiting_inbound')
        """
    )

    await pool.execute(
        """
        UPDATE welcome_deliveries w
        SET phone=r.phone, status='retry', attempts=0, next_attempt_at=now()
        FROM care_circle_siblings r
        WHERE w.recipient_kind='sibling'
          AND w.recipient_id=r.id
          AND w.phone <> r.phone
          AND r.verified
          AND w.status IN ('failed','disabled','awaiting_inbound')
        """
    )

    await pool.execute(
        """
        UPDATE welcome_deliveries w
        SET phone=r.phone, status='retry', attempts=0, next_attempt_at=now()
        FROM parents r
        WHERE w.recipient_kind='parent'
          AND w.recipient_id=r.id
          AND w.phone <> r.phone
          AND r.deleted_at IS NULL
          AND w.status IN ('failed','disabled','awaiting_inbound')
        """
    )

    # Keep the existing reply-notification recovery behavior.
    from services.notifications import recover_contact  # noqa: F401

    await pool.execute(
        """
        UPDATE reply_notifications n
        SET status='pending',
            to_phone=u.phone,
            sid=NULL,
            attempts=0,
            next_attempt_at=now(),
            detail=NULL
        FROM users u, parent_replies r
        WHERE r.id=n.reply_id
          AND n.recipient_kind='user'
          AND n.recipient_id=u.id
          AND n.to_phone <> u.phone
          AND u.deleted_at IS NULL
          AND n.status IN ('failed','disabled','blocked_policy','awaiting_template')
          AND r.created_at > now() - interval '48 hours'
        """
    )


async def welcome_parent_and_child(parent, owner, require_activation=False):
    if require_activation and not await get_pool().fetchval(
        "SELECT whatsapp_activated FROM activation_state WHERE user_id=$1",
        parent["user_id"],
    ):
        return

    if parent.get("opted_out_at") or parent.get("deleted_at"):
        return

    parent_display = parent.get("preferred_name") or parent["name"]
    child_display = (owner.get("name") or "there").split()[0]

    # Parent receives:
    # Hi <parent>! This is AYANA checking in for <child>.
    await enqueue(
        get_pool(),
        f"parent:{parent['id']}",
        parent["phone"],
        {
            "name": parent_display,
            "checking_for": child_display,
            "language": _safe_lang(parent.get("language")),
            "purpose": "parent",
        },
        parent["id"],
        "parent",
    )

    # Child receives the dedicated verified-account welcome template.
    await queue_child(owner, parent_display)

    # Issue #0 fix: unblock child welcomes stuck in 'awaiting_consent'.
    # This happens when the welcome was queued at email-verification time
    # (before consent was given) and the INSERT ON CONFLICT DO NOTHING in
    # queue_child skipped re-inserting.  By the time activation runs,
    # consent has been given via POST /api/consent, so we can safely retry.
    await get_pool().execute(
        """UPDATE welcome_deliveries
           SET status='pending', attempts=0, next_attempt_at=now()
           WHERE recipient_id=$1
             AND recipient_kind='user'
             AND status IN ('awaiting_consent', 'awaiting_inbound',
                            'configuration_error', 'failed', 'disabled')""",
        owner["id"],
    )

    await drain()