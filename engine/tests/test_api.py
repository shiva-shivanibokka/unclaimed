"""API contract: validation, unknown-field assumptions, response shape."""

import pytest
from fastapi.testclient import TestClient

from unclaimed_engine.app import app
from unclaimed_engine.household import COUNTIES
from unclaimed_engine.programs import PROGRAMS


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
    got = {(a["person"], a["question"]): (a["value"], a["status"]) for a in body["assumptions"]}
    assert got[("a", "immigration_status")] == ("CITIZEN", "unknown")
    assert got[(None, "rent")] == (0, "unknown")
    assert got[("a", "weekly_hours_worked")] == (0, "unknown")
    # The county the engine fell back to is named (read from the engine), not hidden.
    assert got[(None, "county")][0] in COUNTIES
    assert body["statements"]  # assumptions said out loud on the results screen
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
    assert any(a["question"] == "county" for a in body["assumptions"]) == (county is None)


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
        assert p.why or p.explain, f"{p.id} has no explain variables"
        for v in (*p.why, *p.explain):
            assert v in system.variables, (p.id, v)
        for v in p.why:  # reasons are yes/no tests
            assert system.variables[v].value_type is bool, (p.id, v)
        assert set(p.states) <= set(SUPPORTED_STATES), p.id


def test_declined_is_reported_as_declined(client):
    body = client.post("/calculate", json={"state": "IL", "people": HEAD, "declined": ["a.immigration_status", "rent"]}).json()
    status = {(a["person"], a["question"]): a["status"] for a in body["assumptions"]}
    assert status[("a", "immigration_status")] == "declined" and status[(None, "rent")] == "declined"
    assert status[("a", "is_pregnant")] == "unknown"


def test_dictionary_endpoint(client):
    body = client.get("/dictionary").json()
    q = {x["id"]: x for x in body["questions"]}
    assert "CITIZEN" in q["immigration_status"]["options"]  # enum options come from the engine
    assert "UNSPECIFIED" not in q["heating_type"]["options"]  # the engine's "not given" is never an answer
    assert q["employment_income"]["core"] and body["statements"]


def test_next_is_cached_and_thinks_ahead(client):
    from unclaimed_engine import think_ahead
    body = {"state": "IL", "county": "COOK_COUNTY_IL", "people": [{"id": "a", "relationship": "head", "age": 40}]}
    first = client.post("/next", json=body).json()
    assert first["ask"]["question"] == "employment_income" and not first["cached"]
    assert client.post("/next", json=body).json()["cached"]
    think_ahead._pool.submit(lambda: None).result()  # single FIFO worker: prefetch is done
    answered = {**body, "people": [{**body["people"][0], "employment_income": 0}]}
    assert client.post("/next", json=answered).json()["cached"]


def test_results_are_computed_ahead_once_the_interview_stops(client, monkeypatch):
    import threading
    from unclaimed_engine import think_ahead
    from unclaimed_engine.household import Household
    monkeypatch.setattr(think_ahead, "next_question", lambda h: {"stop": True})
    monkeypatch.setattr(think_ahead, "results", lambda h: {"programs": []})
    h, lock = Household(state="CA", people=[{"id": "a", "relationship": "head", "age": 51}]), threading.Lock()
    think_ahead.decide(h, lock)
    think_ahead._pool.submit(lambda: None).result()  # single FIFO worker: prefetch is done
    assert think_ahead.calculate_results(h, lock)[1]  # served from the cache


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
    {"state": "CA", "people": HEAD, "declined": ["a.not_a_question"]},
    {"state": "CA", "people": HEAD, "declined": ["a.employment_income"]},  # answered and declined
    {"state": "CA", "people": HEAD, "declined": ["immigration_status"]},  # person question without a person
    {"state": "CA", "people": HEAD, "declined": [".rent"]},  # empty person prefix
    {"state": "CA", "people": HEAD, "declined": ["rent", "rent"]},  # duplicate
    {"state": "CA", "people": [{"id": "a", "relationship": "head", "age": 40, "immigration_status": "ALIEN"}]},
    {"state": "TX", "people": [{"id": "a", "relationship": "head", "age": 40}]},
    {"state": "CA", "people": [{"id": "a", "relationship": "child", "age": 4}]},  # no head
    {"state": "CA", "county": "COOK_COUNTY_IL", "people": [{"id": "a", "relationship": "head", "age": 40}]},
    {"state": "CA", "people": [{"id": "a", "relationship": "head", "age": 40, "employment_income": -5}]},
])
def test_rejects_invalid_households(client, bad):
    assert client.post("/calculate", json=bad).status_code == 422


def test_declined_is_capped(client):
    # Each declined answer costs what-ifs on every /calculate; the cap bounds one request.
    from unclaimed_engine.dictionary import load
    from unclaimed_engine.household import MAX_DECLINED
    person = [f"a.{q.id}" for q in load().questions if q.entity == "person"]
    body = {"state": "CA", "people": [{"id": "a", "relationship": "head", "age": 40}]}
    assert client.post("/calculate", json={**body, "declined": person[:MAX_DECLINED]}).status_code == 200
    assert client.post("/calculate", json={**body, "declined": person[:MAX_DECLINED + 1]}).status_code == 422


def test_think_ahead_is_keyed_by_the_screening_date():
    from datetime import date
    from unclaimed_engine import think_ahead
    from unclaimed_engine.household import Household
    h = Household(state="IL", people=[{"id": "a", "relationship": "head", "age": 40}])
    # No date given means today: a decision cached yesterday (e.g. before the SNAP year
    # starts on Oct 1) must not be served today.
    assert think_ahead._key(h).endswith(date.today().isoformat())


def test_take_home_is_converted_to_pay_before_taxes(client):
    # IL single adult earning $40,000 in 2026, by hand from official figures:
    # FICA 7.65% (SSA: 6.2% + 1.45% Medicare) = $3,060; federal: standard deduction
    # $16,100, 10% to $12,400 then 12% (IRS Rev. Proc. 2025-32) = $2,620; IL: 4.95% flat
    # (35 ILCS 5/201) after one personal exemption of $2,925 (IDOR Bulletin FY 2026-15)
    # = $1,835.21. Take-home $32,484.79, so converting it back gives $40,000.
    body = {"household": {"state": "IL", "county": "COOK_COUNTY_IL", "as_of": "2026-09-15",
                          "people": [{"id": "a", "relationship": "head", "age": 35}]},
            "person": "a", "question": "employment_income", "take_home": 32_484.79}
    r = client.post("/gross_up", json=body)
    assert r.status_code == 200 and abs(r.json()["gross"] - 40_000) < 5
    assert client.post("/gross_up", json={**body, "question": "rent"}).status_code == 422


def test_zip_lookup_reads_the_crosswalk(client):
    assert client.get("/zip/60011").json()["states"] == {"IL": ["LAKE_COUNTY_IL", "COOK_COUNTY_IL"]}
    assert client.get("/zip/10001").json()["states"] == {}  # New York: not a supported state
    assert client.get("/zip/abc").status_code == 422


def test_plans_carry_the_program_list_names(client):
    ca = client.get("/plans/CA").json()
    snap = next(p for p in PROGRAMS if p.id == "snap")
    card = next(c for c in ca.values() if "snap" in c["programs"])
    assert card["names"]["snap"] == snap.name_in("CA")  # the name from the program list
    assert all(a["url"].startswith("https://") for a in card["apply"])  # channels spelled out
    assert client.get("/plans/TX").status_code == 404


def test_why_lists_only_reasons_to_qualify(client):
    # A parent with a job-insurance offer: that fact explains the ACA credit result but is
    # never a reason to qualify, so it must not appear in `why`.
    r = client.post("/calculate", json={"state": "CA", "county": "LOS_ANGELES_COUNTY_CA", "as_of": "2026-09-15",
                                        "people": [{"id": "a", "relationship": "head", "age": 30, "employment_income": 28_000,
                                                    "has_job_health_insurance": True},
                                                   {"id": "k", "relationship": "child", "age": 4}]}).json()
    labels = {f["variable"]: f["label"] for p in r["programs"] for f in p["explain"]}
    reasons = {labels[v] for p in PROGRAMS for v in p.why if v in labels}
    eligible = [p for p in r["programs"] if p["eligible"]]
    assert eligible and all(set(p["why"]) <= reasons for p in eligible)
    # (Here CalFresh passes the net income test but not the federal gross test: California's
    # broader eligibility, so a reason is only ever a test the household actually met.)
    assert labels["meets_snap_net_income_test"] in next(p for p in eligible if p["id"] == "snap")["why"]
