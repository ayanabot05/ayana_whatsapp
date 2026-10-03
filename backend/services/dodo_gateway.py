"""
dodo_gateway.py — Official Dodo Payments integration for international subscribers.
Handles global recurring autopay (USA, UK, Canada, Europe, Australia, 150+ countries).
"""
import base64
import hashlib
import hmac
import logging
import os
import requests
from fastapi import HTTPException

logger = logging.getLogger("ayana.dodo_gateway")


def enabled() -> bool:
    return bool(os.environ.get("DODO_PAYMENTS_API_KEY"))


def environment() -> str:
    return os.environ.get("DODO_PAYMENTS_ENVIRONMENT", "live_mode")


def base_url() -> str:
    if environment() == "live_mode":
        return "https://live.dodopayments.com"
    return "https://test.dodopayments.com"


def product_id_for_plan(plan: str) -> str | None:
    p = (plan or "").lower()
    if p == "nitya":
        return os.environ.get("DODO_PRODUCT_NITYA", "pdt_0Nowatild17dUhTqBz9lY")
    elif p == "bandham":
        return os.environ.get("DODO_PRODUCT_BANDHAM", "pdt_0Nowb31isv8aA7TkMT953")
    elif p == "raksha":
        return os.environ.get("DODO_PRODUCT_RAKSHA", "pdt_0NowbAblu8oxJukjkMXK7")
    return None


def create_checkout_session(plan: str, user: dict, return_url: str) -> dict:
    api_key = os.environ.get("DODO_PAYMENTS_API_KEY")
    if not api_key:
        raise HTTPException(503, "Dodo Payments is not configured on the server.")

    pdt_id = product_id_for_plan(plan)
    if not pdt_id:
        raise HTTPException(400, f"No Dodo Payments product configured for plan '{plan}'.")

    url = f"{base_url()}/checkouts"
    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json",
    }
    payload = {
        "product_cart": [
            {
                "product_id": pdt_id,
                "quantity": 1,
            }
        ],
        "customer": {
            "email": user.get("email") or "",
            "name": user.get("name") or "AYANA Member",
        },
        "return_url": return_url,
        "metadata": {
            "user_id": str(user["id"]),
            "plan": plan,
        },
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=20)
        if resp.status_code not in (200, 201):
            logger.error("[dodo] Checkout creation failed: %s %s", resp.status_code, resp.text)
            raise HTTPException(502, f"Dodo Payments error: {resp.text}")
        data = resp.json()
        return {
            "checkout_url": data.get("checkout_url"),
            "session_id": data.get("session_id"),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[dodo] Failed to connect to Dodo Payments: %s", exc)
        raise HTTPException(503, f"Unable to reach Dodo Payments gateway: {exc}")


def verify_webhook(payload: bytes, headers: dict) -> bool:
    secret = os.environ.get("DODO_PAYMENTS_WEBHOOK_KEY", "").strip()
    if not secret:
        logger.warning("[dodo] Webhook received but DODO_PAYMENTS_WEBHOOK_KEY not set")
        return False

    sig_header = headers.get("webhook-signature") or headers.get("Webhook-Signature") or ""
    msg_id = headers.get("webhook-id") or headers.get("Webhook-Id") or ""
    msg_timestamp = headers.get("webhook-timestamp") or headers.get("Webhook-Timestamp") or ""

    if not sig_header:
        return False

    try:
        clean_secret = secret[6:] if secret.startswith("whsec_") else secret
        key = base64.b64decode(clean_secret)
        to_sign = f"{msg_id}.{msg_timestamp}.".encode("utf-8") + payload
        expected_sig = base64.b64encode(hmac.new(key, to_sign, hashlib.sha256).digest()).decode("utf-8")
        signatures = [s.split(",", 1)[1] if "," in s else s for s in sig_header.split(" ")]
        return any(hmac.compare_digest(expected_sig, s) for s in signatures)
    except Exception as exc:
        logger.error("[dodo] Webhook signature verification error: %s", exc)
        return False
