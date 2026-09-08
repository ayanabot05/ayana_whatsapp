"""Seed a Raksha user + parent (Asia/Kolkata) with the founder's exact
'fake data' scenario: 9 sends (UTC 01:30..04:04 + one 16:14) and only 4 replies.
Prints login creds + parent_id + period for report verification."""
import os
import subprocess
from datetime import datetime, timezone

import requests

BASE = "http://localhost:8001/api"
PG = ["psql", "-h", "127.0.0.1", "-p", "5432", "-U", "ayana", "-d", "ayana", "-tAc"]
ENV = {**os.environ, "PGPASSWORD": "ayana"}


def sql(q):
    return subprocess.run(PG + [q], env=ENV, capture_output=True, text=True, check=True).stdout.strip()


def main():
    suffix = os.urandom(3).hex()
    digits = str(int(suffix, 16))[:5].ljust(5, "0")
    email = f"report_{suffix}@example.com"
    pwd = "Secret@123"
    own_phone = f"+9198765{digits}"

    r = requests.post(f"{BASE}/auth/register", json={
        "name": "Report Tester", "email": email, "phone": own_phone, "password": pwd})
    r.raise_for_status()
    tok = r.json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    code = requests.post(f"{BASE}/auth/otp/send", json={"phone": own_phone}, headers=h).json()["dev_code"]
    requests.post(f"{BASE}/auth/otp/verify", json={"phone": own_phone, "code": code}, headers=h).raise_for_status()

    sql(f"update payment_state set plan='raksha' where user_id=(select id from users where email='{email}')")

    dad_phone = f"+9199{digits}001"
    r = requests.post(f"{BASE}/parents", json={
        "name": "Dady", "relationship": "father", "language": "en",
        "phone": dad_phone, "timezone": "Asia/Kolkata"}, headers=h)
    r.raise_for_status()
    pid = r.json()["id"]
    uid = sql(f"select id from users where email='{email}'").splitlines()[0]
    sched = sql(f"insert into schedules (parent_id, user_id, mode, messages, active) values ('{pid}','{uid}','raksha','[]'::jsonb,true) returning id").splitlines()[0]

    def U(h_, m, day):
        return datetime(2026, 9, day, h_, m, tzinfo=timezone.utc).isoformat()

    sends = [
        (U(16, 14, 7), "2026-09-07", "goodnight"),
        (U(1, 30, 8), "2026-09-08", "medicine_reminder"),
        (U(2, 4, 8), "2026-09-08", "medicine_reminder"),
        (U(2, 30, 8), "2026-09-08", "morning_hello"),
        (U(2, 34, 8), "2026-09-08", "medicine_reminder"),
        (U(3, 4, 8), "2026-09-08", "medicine_reminder"),
        (U(3, 4, 8), "2026-09-08", "morning_hello"),
        (U(3, 34, 8), "2026-09-08", "morning_hello"),
        (U(4, 4, 8), "2026-09-08", "morning_hello"),
    ]
    for i, (ts, dk, cat) in enumerate(sends):
        sql(f"insert into message_logs (user_id, parent_id, schedule_id, message_index, day_key, category, body, msg_type, status, created_at) "
            f"values ('{uid}','{pid}','{sched}',{i},'{dk}','{cat}','hi','checkin','sent','{ts}')")
    for j, (hh, mm) in enumerate([(4, 30), (4, 31), (4, 32), (4, 33)]):
        sql(f"insert into parent_replies (user_id, parent_id, from_phone, body, intent, is_voice, created_at) "
            f"values ('{uid}','{pid}','919','ok','feeling:good',false,'{U(hh, mm, 8)}')")

    print(f"EMAIL={email}")
    print(f"PASSWORD={pwd}")
    print(f"PARENT_ID={pid}")
    print("PERIOD=2026-09")


if __name__ == "__main__":
    main()
