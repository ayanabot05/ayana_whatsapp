import pytest
import uuid

def _setup_parent(api_client, api_url, headers):
    r = api_client.post(f"{api_url}/parents", json={
        "name": "Mom", "relationship": "mother", "phone": "+919000000000",
        "language": "en", "timezone": "Asia/Kolkata"
    }, headers=headers)
    assert r.status_code == 200
    return r.json()["id"]

def test_emergency_contacts_crud(api_client, api_url, fresh_user):
    h = fresh_user["headers"]
    pid = _setup_parent(api_client, api_url, h)
    
    # Get initially empty
    r = api_client.get(f"{api_url}/parents/{pid}/emergency-contacts", headers=h)
    assert r.status_code == 200
    assert r.json()["contacts"] == []
    
    # Set valid contacts
    contacts = [{"name": "C1", "phone": "123"}, {"name": "C2", "phone": "456"}]
    r = api_client.put(f"{api_url}/parents/{pid}/emergency-contacts", json={"contacts": contacts}, headers=h)
    assert r.status_code == 200
    
    r = api_client.get(f"{api_url}/parents/{pid}/emergency-contacts", headers=h)
    assert len(r.json()["contacts"]) == 2

    # Assuming models.py enforces max 5 limit on EmergencyContactsInput
    # Let's try 6 contacts
    six_contacts = [{"name": f"C{i}", "phone": f"{i}"} for i in range(6)]
    r = api_client.put(f"{api_url}/parents/{pid}/emergency-contacts", json={"contacts": six_contacts}, headers=h)
    # The prompt says max 5 enforcement, it should be a 4xx
    assert r.status_code in (400, 422)

def test_emergency_events(api_client, api_url, fresh_user, admin_headers):
    h = fresh_user["headers"]
    pid = _setup_parent(api_client, api_url, h)
    
    # Trigger an emergency event via replies simulate
    r = api_client.post(f"{api_url}/replies/simulate", json={"parent_id": pid, "text": "emergency help"}, headers=h)
    assert r.status_code == 200
    
    r = api_client.get(f"{api_url}/parents/{pid}/emergency-events", headers=h)
    assert r.status_code == 200
    events = r.json()
    assert len(events) >= 1
    event_id = events[0]["id"]
    assert events[0]["status"] == "open"
    
    # Status transitions
    # open -> reviewed
    r = api_client.put(f"{api_url}/emergency-events/{event_id}", json={"status": "reviewed", "resolution_note": "checking"}, headers=h)
    assert r.status_code == 200
    assert r.json()["event"]["status"] == "reviewed"
    
    # reviewed -> resolved
    r = api_client.put(f"{api_url}/emergency-events/{event_id}", json={"status": "resolved"}, headers=h)
    assert r.status_code == 200
    assert r.json()["event"]["status"] == "resolved"
    
    # false positive
    # Trigger another one
    api_client.post(f"{api_url}/replies/simulate", json={"parent_id": pid, "text": "hospital"}, headers=h)
    events2 = api_client.get(f"{api_url}/parents/{pid}/emergency-events", headers=h).json()
    event_id2 = events2[0]["id"]
    
    r = api_client.put(f"{api_url}/emergency-events/{event_id2}", json={"status": "false_positive"}, headers=h)
    assert r.status_code == 200
    assert r.json()["event"]["status"] == "false_positive"
    
    # Non-owner -> 403 / 404
    h2 = _register_new(api_client)
    r = api_client.put(f"{api_url}/emergency-events/{event_id2}", json={"status": "reviewed"}, headers=h2)
    assert r.status_code in (403, 404)
    
    # Invalid event ID
    r = api_client.put(f"{api_url}/emergency-events/000000000000000000000000", json={"status": "reviewed"}, headers=h)
    assert r.status_code == 404
    
    # Admin override
    r = api_client.put(f"{api_url}/admin/emergency-events/{event_id2}", json={"status": "resolved"}, headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["event"]["status"] == "resolved"

def _register_new(api_client):
    import uuid
    unique = uuid.uuid4().hex[:8]
    payload = {"name": f"TEST_{unique}", "email": f"test_{unique}@example.com",
               "phone": "+919876500000", "password": "test1234"}
    r = api_client.post("/api/auth/register", json=payload)
    return {"Authorization": f"Bearer {r.json()['token']}"}
