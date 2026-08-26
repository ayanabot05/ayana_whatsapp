import pytest
from unittest.mock import patch, MagicMock

@pytest.fixture
def mock_stripe():
    with patch("payments.stripe.checkout.Session.create_async") as m_create:
        with patch("payments.stripe.checkout.Session.retrieve_async") as m_retrieve:
            with patch("payments.stripe.Webhook.construct_event") as m_construct:
                yield m_create, m_retrieve, m_construct

def test_stripe_webhook_valid(api_client, api_url, fresh_user, mock_stripe):
    m_create, m_retrieve, m_construct = mock_stripe
    
    # Create checkout first
    h = fresh_user["headers"]
    import os
    os.environ["PAYMENTS_ENABLED"] = "true"
    os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_test"
    
    m_create.return_value = MagicMock(id="cs_test_123", url="http://checkout")
    r = api_client.post(f"{api_url}/payment/checkout", json={"plan": "bandham", "billing": "month", "origin_url": "http://test"}, headers=h)
    assert r.status_code == 200
    session_id = r.json().get("session_id") or "cs_test_123"
    
    # Webhook
    m_construct.return_value = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": session_id,
                "payment_status": "paid"
            }
        }
    }
    
    r = api_client.post(f"{api_url}/webhook/stripe", json={}, headers={"Stripe-Signature": "sig_test"})
    assert r.status_code == 200
    
    # Check status
    r = api_client.get(f"{api_url}/payments/status/{session_id}")
    assert r.status_code == 200
    assert r.json()["payment_status"] == "paid"
    
    os.environ["PAYMENTS_ENABLED"] = "false"

def test_stripe_webhook_invalid_signature(api_client, api_url, mock_stripe):
    m_create, m_retrieve, m_construct = mock_stripe
    import stripe
    m_construct.side_effect = stripe.error.SignatureVerificationError("invalid sig", "sig")
    
    import os
    os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_test"
    
    r = api_client.post(f"{api_url}/webhook/stripe", json={}, headers={"Stripe-Signature": "bad_sig"})
    assert r.status_code == 400

def test_payment_status(api_client, api_url, fresh_user, mock_stripe):
    m_create, m_retrieve, m_construct = mock_stripe
    
    import os
    os.environ["PAYMENTS_ENABLED"] = "true"
    
    h = fresh_user["headers"]
    m_create.return_value = MagicMock(id="cs_test_999", url="http://checkout")
    r = api_client.post(f"{api_url}/payment/checkout", json={"plan": "bandham", "billing": "month", "origin_url": "http://test"}, headers=h)
    assert r.status_code == 200
    session_id = r.json().get("session_id") or "cs_test_999"
    
    m_retrieve.return_value = MagicMock(payment_status="unpaid", status="open")
    r = api_client.get(f"{api_url}/payments/status/{session_id}")
    assert r.status_code == 200
    assert r.json()["payment_status"] == "pending"
    
    m_retrieve.return_value = MagicMock(payment_status="paid", status="complete")
    r = api_client.get(f"{api_url}/payments/status/{session_id}")
    assert r.status_code == 200
    assert r.json()["payment_status"] == "paid"
    
    # Idempotent double check
    r = api_client.get(f"{api_url}/payments/status/{session_id}")
    assert r.status_code == 200
    assert r.json()["payment_status"] == "paid"
    
    os.environ["PAYMENTS_ENABLED"] = "false"
