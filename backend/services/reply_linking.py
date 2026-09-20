"""Evidence-based association shared by the inbox, timeline and reports.

Never consume the next chronological reply: an unquoted message is a general
message, not evidence that a medicine was taken. Parent IDs are part of every key.
"""
from collections import defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def utc(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def parent_zone(name):
    return ZoneInfo(name or 'Asia/Kolkata')


def linked_replies(logs, replies):
    by_sid = {(str(l['parent_id']), l.get('sid')): str(l['id']) for l in logs if l.get('sid')}
    by_id = {str(l['id']): str(l['parent_id']) for l in logs}
    linked, general = defaultdict(list), []
    for raw in sorted(replies, key=lambda r: utc(r['created_at'])):
        reply = dict(raw)
        parent = str(reply['parent_id'])
        log_id = by_sid.get((parent, reply.get('context_id')))
        # Explicit means an audited association, not an old time/category guess.
        if not log_id and not reply.get('context_id') and reply.get('association_source') == 'explicit':
            candidate = str(reply.get('message_log_id'))
            if by_id.get(candidate) == parent:
                log_id = candidate
        if log_id:
            linked[log_id].append(reply)
        else:
            general.append(reply)
    return dict(linked), general


def response_state(replies):
    """A response is distinct from a confirmed action (e.g. medicine taken)."""
    for reply in reversed(replies):
        if not reply.get('button_payload'):
            continue
        action = (reply.get('intent') or '').split(':')[0]
        if action in ('done', 'pending', 'skip', 'arrived', 'on_way', 'activity_done'):
            return action
    return 'replied' if replies else None


def public_reply(reply, zone):
    fields = ('id', 'parent_id', 'body', 'transcription', 'is_voice', 'intent', 'read_at', 'created_at')
    result = {k: reply.get(k) for k in fields}
    result['id'], result['parent_id'] = str(reply['id']), str(reply['parent_id'])
    result['created_at'] = utc(reply['created_at']).isoformat()
    result['display_time'] = utc(reply['created_at']).astimezone(zone).strftime('%d %b, %I:%M %p %Z')
    if result['read_at']:
        result['read_at'] = utc(result['read_at']).isoformat()
    result['notifications'] = reply.get('notifications', [])
    return result


def build_parent_days(parent, logs, replies):
    zone = parent_zone(parent.get('timezone'))
    links, general = linked_replies(logs, replies)
    days = {}

    def day_for(stamp):
        key = utc(stamp).astimezone(zone).date().isoformat()
        return days.setdefault(key, {'day_key': key, 'total': 0, 'replied': 0, 'messages': [], 'general_replies': []})

    for log in sorted(logs, key=lambda l: utc(l['created_at'])):
        day = day_for(log['created_at'])
        responses = links.get(str(log['id']), [])
        rendered = [public_reply(r, zone) for r in responses]
        day['messages'].append({
            'id': str(log['id']), 'category': log['category'], 'msg_type': log['msg_type'],
            'body': log.get('body') or '', 'status': log['status'],
            'delivery_status': log.get('delivery_status'), 'detail': log.get('detail'),
            'created_at': utc(log['created_at']).isoformat(),
            'time': utc(log['created_at']).astimezone(zone).strftime('%I:%M %p %Z'),
            'replied': bool(responses), 'reply_status': response_state(responses),
            'replies': rendered, 'reply': rendered[-1] if rendered else None,
        })
        day['total'] += 1
        day['replied'] += int(bool(responses))
        # A late reply is visible on its received day as well, explicitly linked.
        for reply in responses:
            reply_day = day_for(reply['created_at'])
            if reply_day is not day:
                reply_day.setdefault('late_replies', []).append({**public_reply(reply, zone), 'message_id': str(log['id']), 'category': log['category'], 'sent_at': utc(log['created_at']).isoformat()})
    for reply in general:
        day_for(reply['created_at'])['general_replies'].append(public_reply(reply, zone))
    return [days[k] for k in sorted(days, reverse=True)]