"""API contract: validation, unknown-field assumptions, response shape."""

import pytest
from fastapi.testclient import TestClient

from unclaimed_engine.app import app
from unclaimed_engine.household import COUNTIES


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
    # The county the engine fell back to is named (read from the engine), not hidden.
    county = [x for x in body["assumptions"] if x.startswith("county=")]
    assert len(county) == 1 and county[0].split("=")[1].split()[0] in COUNTIES
    ids = {p["id"] for p in body["programs"]}
    assert "il_eitc" in ids and "ca_eitc" not in ids  # only the household's state


HEAD = [{"id": "a", "relationship": "head", "age": 40, "employment_income": 30_000}]


@pytest.mark.parametrize("state,zip_code,county,candidates", [
    ("CA", "94110", "SAN_FRANCISCO_COUNTY_CA", ["SAN_FRANCISCO_COUNTY_CA"]),  # 100% one county
    ("IL", "60011", None, ["LAKE_COUNTY_IL", "COOK_COUNTY_IL"]),  # 70/30 split: ask
])
def test_zip_to_county(client, state, zip_code, county, candidates):
    body = client.post("/calculate", json={"state": state, "zip": zip_code, "people": HEAD}).json()
    assert body["county"] == county and body["county_candidates"] == candidates
    assert any(a.startswith("county=") for a in body["assumptions"]) == (county is None)


@pytest.mark.parametrize("zip_code", ["60011", "60015"])  # 30% and 5% of residents in Cook
def test_given_county_wins_when_it_contains_the_zip(client, zip_code):
    body = client.post("/calculate", json={"state": "IL", "zip": zip_code, "county": "COOK_COUNTY_IL", "people": HEAD}).json()
    assert body["county"] == "COOK_COUNTY_IL"


def test_program_names_per_state(client):
    names = {s: {p["id"]: p["name"] for p in client.post("/calculate", json={"state": s, "people": HEAD}).json()["programs"]}
             for s in ("CA", "IL")}
    assert names["CA"]["snap"] == "CalFresh" and "CalFresh" not in names["IL"]["snap"]


def test_overload_returns_503(client, monkeypatch):
    import threading
    from unclaimed_engine import app as app_module
    monkeypatch.setattr(app_module, "_slots", threading.BoundedSemaphore(1))
    app_module._slots.acquire()  # the only slot is taken
    assert client.post("/calculate", json={"state": "IL", "people": HEAD}).status_code == 503
    assert client.get("/health").status_code == 200


def test_programs_point_at_real_engine_variables():
    # After a PolicyEngine upgrade, a renamed variable must fail the build, not return $0.
    from policyengine_us.system import system
    from unclaimed_engine.programs import PROGRAMS, SUPPORTED_STATES
    for p in PROGRAMS:
        assert p.variable in system.variables, p.id
        assert p.eligibility is None or p.eligibility in system.variables, p.id
        assert p.explain, f"{p.id} has no explain variables"
        for v in p.explain:
            assert v in system.variables, (p.id, v)
        assert set(p.states) <= set(SUPPORTED_STATES), p.id


def test_programs_list(client):
    ids = {p["id"] for p in client.get("/programs").json()}
    assert {"snap", "eitc", "medicaid", "ca_eitc", "il_eitc"} <= ids


@pytest.mark.parametrize("bad", [
    {"state": "CA", "zip": "60601", "people": HEAD},  # Chicago ZIP, California household
    {"state": "IL", "zip": "62401", "county": "COOK_COUNTY_IL", "people": HEAD},  # county doesn't contain the ZIP
    {"state": "CA", "as_of": "1990-06-01", "people": HEAD},  # outside the rules we test
    {"state": "CA", "as_of": "2099-06-01", "people": HEAD},
    {"state": "CA", "people": [{"id": "a", "relationship": "head", "age": 40, "employment_income": 1e300}]},
    {"state": "CA", "people": [{"id": "a", "relationship": "head", "age": 40, "self_employment_income": -1e12}]},
    {"state": "CA", "people": [{"id": "a", "relationship": "head", "age": 30},
                               {"id": "b", "relationship": "child", "age": 70}]},  # child older than head
    {"state": "CA", "county": "SAN_FRANCISCO_CA", "people": HEAD},  # not a county name
    {"state": "CA", "people": [{"id": "a", "relationship": "head", "age": 40, "immigration_status": "ALIEN"}]},
    {"state": "TX", "people": [{"id": "a", "relationship": "head", "age": 40}]},
    {"state": "CA", "people": [{"id": "a", "relationship": "child", "age": 4}]},  # no head
    {"state": "CA", "county": "COOK_COUNTY_IL", "people": [{"id": "a", "relationship": "head", "age": 40}]},
    {"state": "CA", "people": [{"id": "a", "relationship": "head", "age": 40, "employment_income": -5}]},
])
def test_rejects_invalid_households(client, bad):
    assert client.post("/calculate", json=bad).status_code == 422
