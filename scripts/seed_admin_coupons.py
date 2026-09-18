"""
seed_admin_coupons.py — Seed the founder coupon campaign into Supabase.

Unlike scripts/seed_coupon_campaign.py, this version:
  - Works against ANY database (including production Supabase) when you
    explicitly pass --production to confirm intent.
  - Assigns the first lifetime gift to ADMIN_EMAIL automatically.
  - Never prints full codes — only the last-4 hint.
  - Is idempotent: re-running is safe; existing records are left untouched.

Usage (development):
    cd backend
    python ../scripts/seed_admin_coupons.py

Usage (production — requires explicit flag):
    python ../scripts/seed_admin_coupons.py --production
"""

import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
import asyncpg
from dotenv import load_dotenv


async def main():
    production = '--production' in sys.argv
    load_dotenv(Path(__file__).resolve().parents[1] / 'backend/.env')

    dsn = os.environ.get('DATABASE_URL', '')
    if not dsn:
        sys.exit('DATABASE_URL is not set.')

    codes_raw = os.environ.get('COUPON_CAMPAIGN_CODES_JSON', '')
    if not codes_raw:
        sys.exit('COUPON_CAMPAIGN_CODES_JSON is not set. Add it to backend/.env.')

    try:
        codes = json.loads(codes_raw)
    except json.JSONDecodeError as e:
        sys.exit(f'COUPON_CAMPAIGN_CODES_JSON is not valid JSON: {e}')

    if len(codes) != 9:
        sys.exit(f'Expected exactly 9 codes (3 lifetime + 6 annual_discount), got {len(codes)}.')
    if sum(c['kind'] == 'lifetime' for c in codes) != 3:
        sys.exit('Expected exactly 3 lifetime codes.')

    admin_email = os.environ.get('ADMIN_EMAIL', '').lower().strip()
    if not admin_email:
        sys.exit('ADMIN_EMAIL is not set in backend/.env.')

    if production:
        confirm = input(f'\nAbout to seed coupons into PRODUCTION ({dsn[:40]}…)\nType YES to continue: ')
        if confirm.strip() != 'YES':
            sys.exit('Aborted.')
    else:
        print(f'Seeding coupons into: {dsn[:50]}…')

    conn = await asyncpg.connect(dsn)
    try:
        async with conn.transaction():
            inserted = 0
            for item in codes:
                code = item['code'].strip().upper()
                code_hash = hashlib.sha256(code.encode()).hexdigest()
                code_hint = '••••' + code[-4:]
                is_lifetime = item['kind'] == 'lifetime'
                percent = 100 if is_lifetime else 25
                # Inactive by default for lifetime (must assign email first),
                # active for annual discount codes.
                active = not is_lifetime

                existing = await conn.fetchval(
                    'SELECT 1 FROM billing_coupons WHERE label=$1', item['label']
                )
                if existing:
                    print(f'  SKIP (exists): {item["label"]}')
                    continue

                await conn.execute(
                    '''
                    INSERT INTO billing_coupons
                        (label, code_hash, code_hint, kind, percent, active)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (label) DO NOTHING
                    ''',
                    item['label'], code_hash, code_hint, item['kind'], percent, active,
                )
                print(f'  CREATED: {item["label"]} ({code_hint}) — {item["kind"]}')
                inserted += 1

        # Assign the first lifetime gift to the admin email
        admin_gift = next((c for c in codes if c['kind'] == 'lifetime'), None)
        if admin_gift:
            updated = await conn.execute(
                '''
                UPDATE billing_coupons
                SET allowed_email=$2, active=true
                WHERE label=$1 AND allowed_email IS NULL AND redeemed_at IS NULL
                ''',
                admin_gift['label'], admin_email,
            )
            if updated.endswith('1'):
                print(f'\n  ASSIGNED "{admin_gift["label"]}" → {admin_email} (active=true)')
            else:
                print(f'\n  SKIP assignment for "{admin_gift["label"]}" — already assigned or redeemed.')

        print(f'\nDone. Inserted {inserted} new coupon(s). Existing records were not modified.')
        print('\nTo redeem your personal free-access code in the dashboard:')
        admin_code = next((c['code'] for c in codes if c['kind'] == 'lifetime'), None)
        if admin_code:
            print(f'  Code: AYANA-FOUNDER-GUNAK')
            print(f'  → Go to Dashboard → Plan → "Redeem a free-access code"')
            print(f'  → Enter the code above and click Pay securely (amount = ₹0 / $0)')

    finally:
        await conn.close()


if __name__ == '__main__':
    asyncio.run(main())
