"""The page's HTTP side: caching, and who a client is behind the load balancer."""

from types import SimpleNamespace

from fastapi.testclient import TestClient

from simulator import app as sim


def test_page_and_files_are_revalidated_on_every_load():
    client = TestClient(sim.app)
    assert client.get("/").headers["cache-control"] == "no-cache"
    assert client.get("/static/app.js").headers["cache-control"] == "no-cache"


def test_client_is_the_address_the_balancer_added():
    # The load balancer appends the real client address; anything before it is the client's.
    assert sim.client_ip({"x-forwarded-for": "9.9.9.9, 1.1.1.1"}, None) == "1.1.1.1"
    assert sim.client_ip({}, SimpleNamespace(host="2.2.2.2")) == "2.2.2.2"
