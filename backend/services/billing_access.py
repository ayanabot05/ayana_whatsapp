"""Prepaid access, one activation-based trial, and explicitly sponsored accounts."""
from calendar import monthrange
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from pricing import resolve_plan_id

RANK = {'nitya':0,'bandham':1,'raksha':2}


def add_period(start,billing):
    months = 12 if billing=='year' else 1
    index = start.year*12+start.month-1+months
    year,month = divmod(index,12)
    month += 1
    return start.replace(year=year,month=month,day=min(start.day,monthrange(year,month)[1]))


async def access(conn,user_id):
    now = datetime.now(timezone.utc)
    if await conn.fetchval('SELECT role FROM users WHERE id=$1',user_id)=='admin':
        return {'allowed':True,'plan':'raksha','status':'admin','lifetime':True,'expires_at':None,'auto_renews':False}
    state = await conn.fetchrow('SELECT * FROM payment_state WHERE user_id=$1',user_id)

    active_sub = await conn.fetchrow(
        """SELECT * FROM billing_subscriptions
           WHERE user_id=$1
             AND status IN ('active','cancelled','halted','completed')
             AND current_period_start <= $2 AND current_period_end > $2
           ORDER BY CASE plan WHEN 'raksha' THEN 2 WHEN 'bandham' THEN 1 ELSE 0 END DESC, created_at DESC
           LIMIT 1""",
        user_id, now,
    )
    if active_sub:
        return {
            'allowed': True,
            'plan': active_sub['plan'],
            'status': 'subscribed',
            'lifetime': False,
            'expires_at': active_sub['current_period_end'],
            'auto_renews': active_sub['status'] == 'active' and not active_sub['cancel_at_period_end'],
            'subscription_id': str(active_sub['id']),
        }

    grants = await conn.fetch('SELECT * FROM access_grants WHERE user_id=$1 AND revoked_at IS NULL AND starts_at<=$2 AND (ends_at IS NULL OR ends_at>$2)',user_id,now)
    if grants:
        best = max(grants,key=lambda g:(RANK.get(g['plan'],0),g['ends_at'] is None,g['ends_at'] or now))
        if state and state['legacy_paid_plan'] and RANK.get(resolve_plan_id(state['legacy_paid_plan']),0)>RANK[best['plan']]:
            return {'allowed':True,'plan':resolve_plan_id(state['legacy_paid_plan']),'status':'legacy_paid','lifetime':False,'expires_at':None,'auto_renews':False}
        return {'allowed':True,'plan':best['plan'],'status':'sponsored' if best['ends_at'] is None else 'active','lifetime':best['ends_at'] is None,'expires_at':best['ends_at'],'auto_renews':False}
    if state and state['legacy_paid_plan']:
        return {'allowed':True,'plan':resolve_plan_id(state['legacy_paid_plan']),'status':'legacy_paid','lifetime':False,'expires_at':None,'auto_renews':False}
    if state and not state['billing_managed']:
        return {'allowed':True,'plan':resolve_plan_id(state['plan'] or 'nitya'),'status':'legacy','lifetime':False,'expires_at':None,'auto_renews':False}
    active_trial = bool(state and state['trial_ends_at'] and state['trial_ends_at']>now)
    return {'allowed':active_trial,'plan':resolve_plan_id(state['plan'] or 'nitya') if state else 'nitya','status':'trial' if active_trial else 'trial_available' if state and not state['trial_started_at'] else 'expired','lifetime':False,'expires_at':state['trial_ends_at'] if state else None,'auto_renews':False}


async def begin_trial(conn,user_id):
    state = await conn.fetchrow('SELECT * FROM payment_state WHERE user_id=$1 FOR UPDATE',user_id)
    if not state or not state['billing_managed']:
        return
    if (await access(conn,user_id))['allowed']:
        return
    if state['trial_started_at']:
        raise HTTPException(402,'Your trial has ended. Choose a paid plan or redeem your free-access code before activating care.')
    await conn.execute("UPDATE payment_state SET trial_started_at=now(),trial_ends_at=now()+interval '7 days',status='trial' WHERE user_id=$1 AND trial_started_at IS NULL",user_id)


async def prorated_credit(conn, user_id, currency):
    """Unused value of the caller's current active prepaid plan, in the
    target currency's smallest subunit (paise/cents). Used when quoting an
    upgrade so unused time on the current plan isn't simply thrown away.

    Only prepaid ("Pay once") grants are eligible — a grant needs a linked
    billing_orders row with a known amount/currency to prorate fairly, and
    only a grant currently in effect (not expired, not already revoked)
    counts. Returns (0, None) when there's nothing to credit, or when the
    active grant was paid in a different currency than the new purchase
    (crediting across currencies would need an exchange rate, which we
    don't have — better to charge full price than guess).
    """
    now = datetime.now(timezone.utc)
    grant = await conn.fetchrow(
        """SELECT g.id, g.starts_at, g.ends_at, o.amount, o.currency AS order_currency
           FROM access_grants g
           JOIN billing_orders o ON o.id = g.order_id
           WHERE g.user_id=$1 AND g.revoked_at IS NULL
             AND g.starts_at <= $2 AND g.ends_at IS NOT NULL AND g.ends_at > $2
           ORDER BY g.ends_at DESC LIMIT 1""",
        user_id, now,
    )
    if not grant or grant['order_currency'] != currency:
        return 0, None
    total_days = max((grant['ends_at'] - grant['starts_at']).days, 1)
    days_remaining = max((grant['ends_at'] - now).days, 0)
    credit = int(grant['amount'] * days_remaining / total_days)
    return credit, grant['id']


async def grant_order(conn,order,lifetime=False,revoke_grant_id=None):
    """Called only under the account billing lock and paid/free order transaction.

    revoke_grant_id: when this order was quoted with a prorated upgrade
    credit (see prorated_credit above), pass the credited grant's id here
    so it's revoked in the same transaction the new grant is created in —
    never before the new grant is confirmed paid, and never leaving both
    grants active at once.
    """
    if await conn.fetchval('SELECT 1 FROM access_grants WHERE order_id=$1',order['id']):
        return
    now = datetime.now(timezone.utc)
    start = now
    state = await conn.fetchrow('SELECT * FROM payment_state WHERE user_id=$1 FOR UPDATE',order['user_id'])
    current = await conn.fetch('SELECT * FROM access_grants WHERE user_id=$1 AND revoked_at IS NULL AND (ends_at IS NULL OR ends_at>$2)',order['user_id'],now)
    if not lifetime:
        # Same-plan renewal/downgrade waits for existing higher/equal paid access.
        # An upgrade (order plan outranks what's held) skips this queueing —
        # it starts immediately, since its price already accounted for the
        # unused time via revoke_grant_id/prorated_credit instead.
        for grant in current:
            if grant['id'] == revoke_grant_id:
                continue
            if RANK[grant['plan']] >= RANK[order['plan']]:
                if grant['ends_at'] is None:
                    raise HTTPException(409,'Lifetime access already covers this account. No payment is needed.')
                start = max(start,grant['ends_at'])
        if state and state['trial_ends_at']:
            start = max(start,state['trial_ends_at'])
    end = None if lifetime else add_period(start,order['billing'])
    await conn.execute('INSERT INTO access_grants(user_id,order_id,plan,starts_at,ends_at) VALUES($1,$2,$3,$4,$5) ON CONFLICT(order_id) DO NOTHING',order['user_id'],order['id'],order['plan'],now if lifetime else start,end)
    if revoke_grant_id:
        await conn.execute(
            "UPDATE access_grants SET revoked_at=now() WHERE id=$1 AND user_id=$2 AND revoked_at IS NULL",
            revoke_grant_id, order['user_id'],
        )
    if lifetime or start <= now:
        await conn.execute("INSERT INTO payment_state(user_id,status,plan,billing,billing_managed) VALUES($1,$2,$3,$4,true) ON CONFLICT(user_id) DO UPDATE SET status=excluded.status,plan=excluded.plan,billing=excluded.billing,billing_managed=true,updated_at=now()",order['user_id'],'sponsored' if lifetime else 'active',order['plan'],order['billing'])
    await conn.execute('UPDATE users SET onboarding_step=greatest(onboarding_step,2) WHERE id=$1',order['user_id'])