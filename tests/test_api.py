"""Endpoint tests.

These exist because a missing module-level import survived the entire suite:
every test imported the app, none of them CALLED it, so a NameError inside a
route handler only surfaced when a real request arrived. Importing a FastAPI
app proves almost nothing about whether its routes work.
"""

from __future__ import annotations

import pytest

# The web layer is an OPTIONAL extra. Importing it unconditionally made the
# entire suite fail at collection when only [dev] was installed -- which is
# exactly what CI did, so every test "failed" for a reason unrelated to any of
# them. Skipping cleanly keeps the failure proportionate to the cause.
pytest.importorskip("fastapi", reason="install the [api] extra to run API tests")

from fastapi.testclient import TestClient  # noqa: E402

from vyuha.api.server import app  # noqa: E402
from vyuha.config import settings  # noqa: E402


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def secured(monkeypatch):
    monkeypatch.setattr(settings, "access_token", "test-token-value")
    import vyuha.api.server as srv

    srv._REQUESTS.clear()
    return TestClient(app)


# ------------------------------------------------------- routes respond


def test_health_actually_executes(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "council_available" in body
    assert "requires_key" in body


def test_status_page_renders(client):
    r = client.get("/status")
    assert r.status_code == 200
    assert "Vyuha is running" in r.text


def test_index_renders(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "VYUHA" in r.text


def test_personas_and_sources_and_coverage(client):
    assert len(client.get("/api/personas").json()) == 10
    assert client.get("/api/sources").json()["summary"]["sources_total"] > 40
    cov = client.get("/api/coverage").json()
    assert cov["real_estate"]["can_answer"] is False
    assert cov["commodity"]["can_answer"] is True


# --------------------------------------------------------------- access


def test_open_when_no_token_configured(monkeypatch):
    """An unset token means open, which is right for a laptop and wrong for a
    public URL. Set explicitly rather than read from the environment, so the
    test does not depend on whether a .env happens to exist."""
    monkeypatch.setattr(settings, "access_token", "")
    import vyuha.api.server as srv

    srv._REQUESTS.clear()
    c = TestClient(app)
    assert c.get("/api/health").json()["requires_key"] is False
    assert c.post("/api/ask", json={"question": "what is the repo rate"}).status_code == 200


def test_expensive_route_requires_the_key(secured):
    r = secured.post("/api/ask/stream", json={"question": "hello there"})
    assert r.status_code == 401
    assert "access key" in r.json()["detail"]


def test_page_and_diagnostics_stay_open_when_secured(secured):
    """A shared link must still load, and stay diagnosable, without the key."""
    assert secured.get("/").status_code == 200
    assert secured.get("/status").status_code == 200
    assert secured.get("/api/health").status_code == 200


def test_health_advertises_that_a_key_is_needed(secured):
    assert secured.get("/api/health").json()["requires_key"] is True


def test_wrong_key_rejected(secured):
    r = secured.post("/api/ask/stream", json={"question": "hi there"},
                     headers={"X-Vyuha-Key": "not-the-token"})
    assert r.status_code == 401


def test_key_accepted_as_header(secured):
    r = secured.post("/api/ask/stream", json={"question": "what is the repo rate"},
                     headers={"X-Vyuha-Key": "test-token-value"})
    assert r.status_code == 200


def test_key_accepted_as_query_param(secured):
    """Needed so a single shareable URL works."""
    r = secured.post("/api/ask/stream?key=test-token-value",
                     json={"question": "what is the repo rate"})
    assert r.status_code == 200


def test_rate_limit_applies_even_with_a_valid_key(secured, monkeypatch):
    """A leaked link should cost a slow afternoon, not an unbounded bill."""
    monkeypatch.setattr(settings, "rate_limit_per_hour", 3)
    import vyuha.api.server as srv

    srv._REQUESTS.clear()
    h = {"X-Vyuha-Key": "test-token-value"}
    codes = [secured.post("/api/ask", json={"question": "what is the repo rate"},
                          headers=h).status_code for _ in range(5)]
    assert 429 in codes, f"rate limit never fired: {codes}"


def test_comparison_uses_constant_time(secured):
    """A plain == leaks the token a byte at a time to a patient attacker."""
    import inspect

    import vyuha.api.server as srv

    src = inspect.getsource(srv.check_access)
    assert "compare_digest" in src


def test_auth_runs_before_body_validation(secured):
    """A malformed body must not reveal the schema to someone without the key.

    With auth as a route dependency FastAPI validated the body first, so an
    invalid request returned 422 regardless of the key -- letting an attacker
    map the API by trial and error. Auth now runs as middleware, ahead of
    validation, so the refusal comes first.
    """
    r = secured.post("/api/ask/stream", json={"question": "x"})   # too short
    assert r.status_code == 401, f"got {r.status_code}: schema leaked before auth"


def test_valid_key_still_gets_normal_validation(secured):
    r = secured.post("/api/ask/stream", json={"question": "x"},
                     headers={"X-Vyuha-Key": "test-token-value"})
    assert r.status_code == 422, "with a key, a bad body should fail validation"


def test_evidence_endpoint_is_also_gated(secured):
    assert secured.get("/api/evidence").status_code == 401
