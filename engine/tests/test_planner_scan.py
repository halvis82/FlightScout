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


def test_legs_with_absurd_detours_are_dropped():
    at = datetime(2030, 1, 1, 8)
    assert not planner._sane(ticket(["SAN", "DEN", "LAX"], at))  # 180 km flown via Denver
    assert planner._sane(ticket(["SAN", "LAX"], at))
    assert planner._sane(ticket(["SAN", "DEN", "KEF", "OSL"], at))  # long haul with normal connections


def test_known_fares_from_the_website_find_layovers(world, monkeypatch):
    monkeypatch.setattr(kiwiweb, "explore", lambda *a, **k: [])  # Kiwi knows nothing today
    found = planner.discover_hubs("SAN", "OSL", world, world, known_from={"FCO": 200, "LAX": 90},
                                  known_to={"FCO": 60, "fra": 150})
    assert found == ["FCO"]  # LAX has no known leg on to Oslo, FRA none from San Diego


def test_nested_ignores_one_slice_round_trip_rows(world, monkeypatch):
    # Google's "choose the return later" rows (return_pending) have one slice
    at = datetime(world.year, world.month, world.day, 7)
    pending = ticket(["SAN", "LAX"], at).model_copy(update={"return_pending": True})
    monkeypatch.setattr(google, "search", lambda q, top_n=3, wide=True: [pending])
    ctx = planner._Ctx(planner.PlanRequest(origins=["SAN"], destinations=["OSL"], depart_start=world))
    assert planner._nested(ctx, ["SAN"], ["OSL"], world, world + timedelta(days=7), ["LAX"]) == []


def test_bad_plan_requests_are_refused():
    with pytest.raises(ValueError):
        planner.PlanRequest(origins=["SAN"], destinations=["OSL"], depart_start=date.today() + timedelta(days=9),
                            depart_end=date.today() + timedelta(days=3))
    with pytest.raises(ValueError):
        planner.PlanRequest(origins=["SAN"], destinations=["OSL"], depart_start=date.today() + timedelta(days=9),
                            currency="dollars")


def test_trip_builder_only_swaps_in_flights_that_still_connect(world, monkeypatch):
    at = datetime(world.year, world.month, world.day, 8)
    leg1 = ticket(["OSL", "CPH"], at, hours=1, price=100, source="kiwi")
    leg2 = ticket(["CPH", "OSL"], at + timedelta(days=3), hours=1, price=100, source="kiwi")
    monkeypatch.setattr(kiwi, "search_range", lambda o, d, lo, hi, cur, nights=None, cabin="economy", adults=1:
                        [leg1] if o == "OSL" else [leg2])
    # Google has a cheaper Copenhagen flight, but it leaves before the first flight lands
    early = ticket(["CPH", "OSL"], at - timedelta(hours=2), hours=1, price=60)
    monkeypatch.setattr(google, "search", lambda q, top_n=3, wide=True: [early] if q.origins == ["CPH"] else [])
    res = planner.build_trip(planner.TripRequest(start="OSL", stops=[planner.TripStop(place="CPH", min_nights=2, max_nights=4)],
                                                 earliest_departure=world))
    for t in res.trips:
        legs = [tk.slices[0] for tk in t.tickets]
        assert all(b.departure > a.arrival for a, b in zip(legs, legs[1:]))


def test_multicity_uses_every_source_and_keeps_the_order(world, monkeypatch):
    from flightscout import multicity

    at = datetime(world.year, world.month, world.day, 8)
    later = world + timedelta(days=5)
    at2 = datetime(later.year, later.month, later.day, 9)
    monkeypatch.setattr(kiwi, "search_range", lambda *a, **k: [ticket(["OSL", "LON"], at, hours=2, price=120, source="kiwi")]
                        if a[0] == "OSL" else [ticket(["LON", "OSL"], at2, hours=2, price=110, source="kiwi")])
    # an earlier leg 2 flight that leaves before leg 1 lands must never be chosen
    monkeypatch.setattr(kiwiweb, "search_window", lambda o, d, lo, hi, *a, **k:
                        [ticket(["LON", "OSL"], at - timedelta(hours=5), hours=2, price=20, source="kiwiweb")] if o[0] != "OSL" else [])
    monkeypatch.setattr(google, "dates", lambda *a, **k: [])
    monkeypatch.setattr(google, "search", lambda q, top_n=3, wide=True: [])

    def fake_full(q, seller_rules=None):  # the airline's own site: cheaper leg 1
        if q.origins[0] == "OSL":
            it = ticket(["OSL", "LON"], at, hours=2, price=60, source="ryanair")
            return SearchResult(query=q, trips=[Trip(tickets=[it], total_price=60, currency="USD")])
        return SearchResult(query=q, trips=[])

    monkeypatch.setattr(multicity, "full_search", fake_full)
    req = multicity.MultiRequest(legs=[multicity.Leg(origins=["OSL"], destinations=["LON"], date=world),
                                       multicity.Leg(origins=["LON"], destinations=["OSL"], date=later)])
    res = multicity.plan_multicity(req)
    best = min(res.trips, key=lambda t: t.total_price)
    assert best.total_price == 170 and best.tickets[0].source == "ryanair"
    for t in res.trips:
        assert t.tickets[1].slices[0].departure > t.tickets[0].slices[-1].arrival
