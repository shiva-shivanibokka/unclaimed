"""API contract: validation, unknown-field assumptions, response shape."""

import pytest
from fastapi.testclient import TestClient

from unclaimed_engine.app import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:  # runs the warm-up
        yield c


def test_health_ready(client):
    assert client.get("/health").json() == {"ok": True, "ready": True}


def test_unknowns_are_reported_as_assumptions(client):
    r = client.post("/calculate", json={
        "state": "IL", "as_of": "2026-09-15",
        "people": [{"id": "a", "relationship": "head", "age": 40, "employment_income": 30_000}],
    })
    assert r.status_code == 200
    body = r.json()
    assert {"a.immigration_status=CITIZEN", "rent=0", "a.weekly_hours_worked=0"} <= set(body["assumptions"])
    assert any(a.startswith("county=unknown") for a in body["assumptions"])
    ids = {p["id"] for p in body["programs"]}
    assert "il_eitc" in ids and "ca_eitc" not in ids  # only the household's state


@pytest.mark.parametrize("bad", [
    {"state": "TX", "people": [{"id": "a", "relationship": "head", "age": 40}]},
    {"state": "CA", "people": [{"id": "a", "relationship": "child", "age": 4}]},  # no head
    {"state": "CA", "county": "COOK_COUNTY_IL", "people": [{"id": "a", "relationship": "head", "age": 40}]},
    {"state": "CA", "people": [{"id": "a", "relationship": "head", "age": 40, "employment_income": -5}]},
])
def test_rejects_invalid_households(client, bad):
    assert client.post("/calculate", json=bad).status_code == 422
