"""The planner end to end with fake sources: layovers found from real fares,
Kiwi leg matrices, nearby airports, airline re-pricing and the fare memory."""

from datetime import date, datetime, timedelta

import pytest
from conftest import ticket

from flightscout import cache, farememory, planner
from flightscout import search as search_mod
from flightscout.models import Destination, SearchResult, Trip
from flightscout.sources import google, kiwi, kiwiweb


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setattr(cache, "DIR", tmp_path)
    monkeypatch.setattr(farememory, "_conn", None)
    monkeypatch.setattr(farememory, "_broken", False)
    day = date.today() + timedelta(days=30)
    at = datetime(day.year, day.month, day.day, 7, 0)

    def fake_google(q, top_n=3, wide=True):
        o, d = q.origins, q.destinations
        if o == ["SAN"] and d == ["OSL"]:
            return [ticket(["SAN", "OSL"], at, hours=12, price=600)]
        if o == ["SAN"] and d == ["FCO"]:
            return [ticket(["SAN", "FCO"], at, hours=12, price=200)]
        if o == ["FCO"] and d == ["OSL"] and q.departure == day + timedelta(days=1):
            return [ticket(["FCO", "OSL"], at + timedelta(days=1), hours=3, price=80)]
        if o == ["SAN"] and "TRF" in d:  # a nearby airport to Oslo
            return [ticket(["SAN", "TRF"], at, hours=13, price=300)]
        return []

    def fake_explore(code, lo, hi, currency, nights=None, limit=300):
        prices = {"SAN": {"FCO": 250, "OSL": 590}, "OSL": {"FCO": 60, "SAN": 610}}[code]
        return [Destination(origin=code, destination=k, price=v, currency="USD", source="kiwiweb")
                for k, v in prices.items()]

    def fake_full_search(q, seller_rules=None):
        # the airline's own site sells the Rome to Oslo leg cheaper
        if q.origins == ["FCO"] and q.destinations == ["OSL"]:
            it = ticket(["FCO", "OSL"], at + timedelta(days=1), hours=3, price=45, source="level")
            return SearchResult(query=q, trips=[Trip(tickets=[it], total_price=45, currency="USD")])
        return SearchResult(query=q, trips=[])

    monkeypatch.setattr(google, "search", fake_google)
    monkeypatch.setattr(kiwi, "search", lambda q: [])
    monkeypatch.setattr(kiwiweb, "search_window", lambda *a, **k: [])
    monkeypatch.setattr(kiwiweb, "explore", fake_explore)
    monkeypatch.setattr(search_mod, "search", fake_full_search)
    return day


def test_discovered_layover_nearby_airport_and_airline_reprice(world):
    req = planner.PlanRequest(origins=["SAN"], destinations=["OSL"], depart_start=world, max_hubs=2,
                              max_stopover_days=1, include_nested_roundtrips=False)
    res = planner.plan(req)
    # Rome isn't a hub on the map for San Diego to Oslo, the fares found it
    assert "FCO" in res.hubs_tried
    via_rome = [t for t in res.trips if t.route == ["SAN", "FCO", "OSL"]]
    assert via_rome and min(t.total_price for t in via_rome) == 245  # 200 + 45 from the airline's own site
    assert any(tk.source == "level" for t in via_rome for tk in t.tickets)
    nearby = [t for t in res.trips if t.kind == "nearby"]
    assert nearby and nearby[0].note.startswith("Lands at TRF")
    assert res.direct and res.direct.total_price == 600


def test_fare_memory_remembers_one_way_legs(world):
    at = datetime(world.year, world.month, world.day, 9, 0)
    farememory.record([ticket(["OSL", "BGO"], at, price=40), ticket(["OSL", "BGO"], at, price=35, source="kiwiweb"),
                       ticket(["OSL", "SVG"], at, price=50, back=at + timedelta(days=3))])  # round trip: not a leg
    assert farememory.cheapest("OSL", "BGO", world, world) == 35
    assert farememory.from_origin("OSL", world, world) == {"BGO": 35}
    assert farememory.to_dest("BGO", world, world) == {"OSL": 35}
    assert farememory.cheapest("OSL", "SVG", world, world) is None


def test_endpoint_note_flags_other_airports():
    at = datetime(2030, 1, 1, 8)
    note = search_mod.endpoint_note(ticket(["SAN", "TRF"], at), ["SAN"], ["OSL"])
    assert note and note.startswith("Lands at TRF") and "km from OSL" in note
    assert search_mod.endpoint_note(ticket(["SAN", "OSL"], at), ["SAN"], ["OSL"]) is None
