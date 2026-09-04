import os
import pytest
import uuid
from fastapi.testclient import TestClient
from server import app

# Read admin credentials from .env to match the live DB
from dotenv import load_dotenv
load_dotenv()

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@ayanabot.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")


# Disable rate limiting during tests to prevent 429 errors on parallel fixtures
@pytest.fixture(autouse=True, scope="session")
def disable_rate_limiter():
    """Disable slowapi limiter for test runs."""
    if hasattr(app.state, "limiter"):
        app.state.limiter.enabled = False
    yield
    # No cleanup needed; process exits after test session

@pytest.fixture(scope="session")
def api_client():
    with TestClient(app) as c:
        yield c

@pytest.fixture(scope="session")
def api_url():
    return "/api"

def _register(client, name="Test User"):
    unique = uuid.uuid4().hex[:8]
    payload = {
        "name": f"TEST_{name}_{unique}",
        "email": f"test_{unique}@example.com",
        "phone": "+919876500000",
        "password": "test1234",
    }
    r = client.post("/api/auth/register", json=payload)
    assert r.status_code == 200, f"Registration failed: {r.text}"
    data = r.json()
    return payload, data["token"], data["user"]

@pytest.fixture(scope="session")
def registered_user(api_client):
    payload, token, user = _register(api_client)
    return {"payload": payload, "token": token, "user": user}

@pytest.fixture(scope="session")
def auth_headers(registered_user):
    return {"Authorization": f"Bearer {registered_user['token']}"}

@pytest.fixture(scope="session")
def admin_headers(api_client):
    r = api_client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    if r.status_code != 200:
        pytest.skip(f"Admin login failed: {r.status_code} {r.text}")
    token = r.json()["token"]
    return {"Authorization": f"Bearer {token}"}

@pytest.fixture
def fresh_user(api_client):
    """A brand-new user with its own token for isolated tests."""
    payload, token, user = _register(api_client, name="Fresh")
    return {"payload": payload, "token": token, "user": user,
            "headers": {"Authorization": f"Bearer {token}"}}
