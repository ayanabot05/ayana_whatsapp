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


async def grant_order(conn,order,lifetime=False):
    """Called only under the account billing lock and paid/free order transaction."""
    if await conn.fetchval('SELECT 1 FROM access_grants WHERE order_id=$1',order['id']):
        return
    now = datetime.now(timezone.utc)
    start = now
    state = await conn.fetchrow('SELECT * FROM payment_state WHERE user_id=$1 FOR UPDATE',order['user_id'])
    current = await conn.fetch('SELECT * FROM access_grants WHERE user_id=$1 AND revoked_at IS NULL AND (ends_at IS NULL OR ends_at>$2)',order['user_id'],now)
    if not lifetime:
        # Same-plan renewal/downgrade waits for existing higher/equal paid access.
        for grant in current:
            if RANK[grant['plan']] >= RANK[order['plan']]:
                if grant['ends_at'] is None:
                    raise HTTPException(409,'Lifetime access already covers this account. No payment is needed.')
                start = max(start,grant['ends_at'])
        if state and state['trial_ends_at']:
            start = max(start,state['trial_ends_at'])
    end = None if lifetime else add_period(start,order['billing'])
    await conn.execute('INSERT INTO access_grants(user_id,order_id,plan,starts_at,ends_at) VALUES($1,$2,$3,$4,$5) ON CONFLICT(order_id) DO NOTHING',order['user_id'],order['id'],order['plan'],now if lifetime else start,end)
    await conn.execute("INSERT INTO payment_state(user_id,status,plan,billing,billing_managed) VALUES($1,$2,$3,$4,true) ON CONFLICT(user_id) DO UPDATE SET status=excluded.status,plan=excluded.plan,billing=excluded.billing,billing_managed=true,updated_at=now()",order['user_id'],'sponsored' if lifetime else 'active',order['plan'],order['billing'])
    await conn.execute('UPDATE users SET onboarding_step=greatest(onboarding_step,2) WHERE id=$1',order['user_id'])