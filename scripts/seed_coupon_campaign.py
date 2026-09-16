"""Seed the requested 3 free gifts + 6 annual discounts, without printing codes.

Codes come from the ignored backend/.env. Idempotent; never re-enables, resets or
rotates a used code. Production seeding requires separate explicit approval.
"""
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse
import asyncpg
from dotenv import load_dotenv


async def main():
    load_dotenv(Path(__file__).resolve().parents[1]/'backend/.env')
    dsn = os.environ['DATABASE_URL']
    if urlparse(dsn).hostname not in ('localhost','127.0.0.1') or os.environ.get('APP_ENV')!='test':
        sys.exit('Refusing to seed coupons outside the isolated test database.')
    codes = json.loads(os.environ['COUPON_CAMPAIGN_CODES_JSON'])
    if len(codes)!=9 or sum(c['kind']=='lifetime' for c in codes)!=3:
        sys.exit('Expected exactly three lifetime gifts and six annual discounts.')
    conn = await asyncpg.connect(dsn)
    try:
        async with conn.transaction():
            for item in codes:
                code = item['code'].strip().upper()
                free = item['kind']=='lifetime'
                await conn.execute('INSERT INTO billing_coupons(label,code_hash,code_hint,kind,percent,active) VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT(label) DO NOTHING',item['label'],hashlib.sha256(code.encode()).hexdigest(),'••••'+code[-4:],item['kind'],100 if free else 25,not free)
        print('Coupon campaign ready: 3 inactive email-bound gifts; 6 single-use annual discounts.')
    finally:
        await conn.close()


if __name__=='__main__':
    asyncio.run(main())