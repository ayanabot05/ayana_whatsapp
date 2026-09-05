"""
test_meta_creds.py — sanity-check META_WA_* credentials before touching
the real AYANA app code (whatsapp.py / templates_data.py).

Usage:
    pip install httpx python-dotenv
    python test_meta_creds.py

Reads META_WA_ACCESS_TOKEN, META_WA_PHONE_NUMBER_ID, META_WA_APP_SECRET
from your .env (or the environment) and does two checks:

  1. GET the phone number's own metadata — confirms token + phone_number_id
     are valid and paired correctly (cheapest possible check, no message
     is sent, no template is consumed).
  2. Sends ONE real approved template message (default: ayana_opener, en)
     to a recipient number you provide — confirms end-to-end template
     sending actually works against your test number.

Run step 1 first. Only run step 2 once step 1 passes.
"""

import os
import sys
import httpx

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("(python-dotenv not installed — reading from real env vars only)")

GRAPH_VERSION = os.environ.get("META_WA_GRAPH_VERSION", "v22.0").strip()
TOKEN = os.environ.get("META_WA_ACCESS_TOKEN", "").strip()
PHONE_ID = os.environ.get("META_WA_PHONE_NUMBER_ID", "").strip()
APP_SECRET = os.environ.get("META_WA_APP_SECRET", "").strip()


def check_env():
    print("── Checking .env values are present ──")
    missing = []
    for name, val in [
        ("META_WA_ACCESS_TOKEN", TOKEN),
        ("META_WA_PHONE_NUMBER_ID", PHONE_ID),
        ("META_WA_APP_SECRET", APP_SECRET),
    ]:
        status = "OK" if val else "MISSING"
        shown = f"{val[:6]}...{val[-4:]}" if val and len(val) > 12 else ("(empty)" if not val else val)
        print(f"  {name}: {status}  ({shown})")
        if not val:
            missing.append(name)
    if missing:
        print(f"\n❌ Missing: {', '.join(missing)}. Fix .env and rerun.")
        sys.exit(1)
    print()


def check_phone_number_metadata():
    print("── Step 1: Verifying token + phone_number_id pair ──")
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{PHONE_ID}"
    try:
        resp = httpx.get(
            url,
            headers={"Authorization": f"Bearer {TOKEN}"},
            params={"fields": "verified_name,display_phone_number,quality_rating,platform_type"},
            timeout=15.0,
        )
        data = resp.json()
        if resp.status_code == 200:
            print("✅ Success. Phone number details:")
            for k, v in data.items():
                print(f"   {k}: {v}")
            return True
        else:
            print(f"❌ Failed (HTTP {resp.status_code}):")
            print(f"   {data}")
            return False
    except Exception as e:
        print(f"❌ Request failed: {e}")
        return False


def send_test_template(to_phone: str, template_name: str = "ayana_opener_en", language: str = "en"):
    print(f"\n── Step 2: Sending real template '{template_name}' ({language}) to {to_phone} ──")
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{PHONE_ID}/messages"
    # NOTE: Meta has these approved as separate resources per language —
    # ayana_opener_en / ayana_opener_te / ayana_opener_hi — NOT one
    # "ayana_opener" name with 3 language variants. The name you pass here
    # must include the _en/_te/_hi suffix or Meta returns "template not
    # found" (see /meta_approved_templates.txt at repo root for the full list).
    # Adjust body params below to match however many {{n}} variables your
    # approved template actually has. ayana_opener_en needs 2: {{1}}=name, {{2}}=relation label.
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language},
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": "Test"},
                        {"type": "text", "text": "Amma"},
                    ],
                }
            ],
        },
    }
    try:
        resp = httpx.post(
            url,
            headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
            json=payload,
            timeout=30.0,
        )
        data = resp.json()
        if resp.status_code == 200:
            msg_id = data.get("messages", [{}])[0].get("id", "")
            print(f"✅ Sent. Message ID: {msg_id}")
            print("   Check the recipient's WhatsApp now.")
        else:
            print(f"❌ Failed (HTTP {resp.status_code}):")
            print(f"   {data}")
            print("\n   Common causes:")
            print("   - Recipient not added as a verified recipient on the test number (max 5)")
            print("   - Template name/language doesn't match an APPROVED template exactly")
            print("   - Wrong number of {{n}} parameters vs. what the template expects")
    except Exception as e:
        print(f"❌ Request failed: {e}")


if __name__ == "__main__":
    check_env()
    ok = check_phone_number_metadata()
    if not ok:
        print("\nFix the above before proceeding to step 2.")
        sys.exit(1)

    print()
    recipient = input("Enter a verified recipient phone number (E.164, e.g. +91XXXXXXXXXX), or press Enter to skip: ").strip()
    if recipient:
        send_test_template(recipient)
    else:
        print("Skipped step 2.")