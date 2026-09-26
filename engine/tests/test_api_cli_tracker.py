from datetime import date, timedelta

from conftest import ticket
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from flightscout import search as search_mod
from flightscout import tracker
from flightscout.api import app
from flightscout.cli import app as cli_app


def test_health_and_engine_key(monkeypatch):
    c = TestClient(app)
    h = c.get("/health").json()
    assert h["ok"] is True
    # the website skips runners below its MIN_API (web/src/lib/local-runner.ts)
    assert h["api"] >= 2
    monkeypatch.setenv("ENGINE_KEY", "secret")
    body = {"origins": ["SAN"], "destinations": ["LAX"], "departure": str(date.today() + timedelta(days=9))}
    assert c.post("/search", json=body).status_code == 401


def test_search_merges_sources_and_converts_currency(monkeypatch, dt):
    a = ticket(["SAN", "LAX"], dt, price=50)
    b = ticket(["SAN", "LAX"], dt, price=40, source="kiwi").model_copy(update={"seller_kind": "ota", "currency": "EUR"})
    monkeypatch.setattr(search_mod, "SOURCES", {"google": lambda q: [a], "kiwi": lambda q: [b],
                                                "booking": lambda q: (_ for _ in ()).throw(RuntimeError("down"))})
    monkeypatch.setattr(search_mod.fx, "convert", lambda amt, frm, to: amt * 2 if frm != to else amt)
    q = search_mod.SearchQuery(origins=["SAN"], destinations=["LAX"], departure=dt.date(), currency="USD",
                               sources=["google", "kiwi", "booking"])
    r = search_mod.search(q)
    assert [t.total_price for t in r.trips] == [50, 80]  # EUR converted, sorted
    assert "booking" in r.errors  # one failing source doesn't sink the search


def test_tracker_sampling_never_divides_by_zero():
    s = date(2026, 12, 1)
    assert tracker._sample(s, s + timedelta(days=10), 1) == [s + timedelta(days=5)]
    assert len(tracker._sample(s, s + timedelta(days=10), 4)) == 4
    assert tracker._sample(s, s, 3) == [s]


def test_cli_airports_and_date_parsing():
    r = CliRunner().invoke(cli_app, ["airports", "cancun"])
    assert r.exit_code == 0 and "CUN" in r.output
    from flightscout.cli import _date
    assert _date("+3") == date.today() + timedelta(days=3)
    assert _date("2026-11-20") == date(2026, 11, 20)
