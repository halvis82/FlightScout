from datetime import timedelta

from conftest import ticket

from flightscout import sellers
from flightscout.models import Trip


def test_itinerary_ids_and_trip_type(dt):
    ow = ticket(["SAN", "LAX", "JFK"], dt)
    rt = ticket(["SAN", "JFK"], dt, back=dt + timedelta(days=7))
    assert ow.trip_type == "oneway" and rt.trip_type == "roundtrip"
    assert ow.id == ticket(["SAN", "LAX", "JFK"], dt).id  # deterministic
    assert ow.id != rt.id


def test_trip_route_and_times(dt):
    a = ticket(["SAN", "LAX"], dt, hours=1)
    b = ticket(["LAX", "DPS"], dt + timedelta(hours=6), hours=18)
    t = Trip(tickets=[a, b], total_price=300, currency="USD", kind="split")
    assert t.route == ["SAN", "LAX", "DPS"]
    assert t.departure == a.slices[0].departure and t.arrival == b.slices[0].arrival


def test_annotate_flags_tight_self_transfer_and_airport_change(dt):
    it = ticket(["OSL", "CPH", "SAN"], dt, hours=2, self_transfer=True)
    it = sellers.annotate(it)
    assert any("self transfer" in w for w in it.warnings)
    it2 = ticket(["OSL", "CPH"], dt)
    it2.slices[0].segments.append(it2.slices[0].segments[0].model_copy(update={"origin": "LHR", "destination": "SAN"}))
    assert any("Airport change" in w for w in sellers.annotate(it2).warnings)


def test_seller_rules_block_and_warn(dt):
    kiwi = ticket(["OSL", "SAN"], dt).model_copy(update={"seller": "Kiwi.com"})
    google = ticket(["OSL", "SAN"], dt).model_copy(update={"seller": "Google Flights"})
    trips = [Trip(tickets=[kiwi], total_price=1, currency="USD"), Trip(tickets=[google], total_price=2, currency="USD")]
    kept = sellers.apply_rules(trips, {"Kiwi.com": "block"})
    assert [t.tickets[0].seller for t in kept] == ["Google Flights"]
    warned = sellers.apply_rules(trips, None)  # Kiwi is on the default warn list
    assert any("warning list" in w for w in warned[0].tickets[0].warnings)


def test_far_below_market_ota_price_gets_a_warning(dt):
    from conftest import ticket
    from flightscout.search import _flag_outliers

    g = ticket(["LIS", "OPO"], dt, price=60.0, source="google")
    bait = ticket(["LIS", "OPO"], dt, price=9.0, source="wego").model_copy(update={"seller_kind": "ota"})
    fair = ticket(["LIS", "OPO"], dt, price=55.0, source="booking").model_copy(update={"seller_kind": "ota"})
    _flag_outliers([g, bait, fair])
    assert any("Far cheaper" in w for w in bait.warnings)
    assert not fair.warnings and not g.warnings


def test_hidden_city_fare_does_not_replace_the_normal_ticket(dt):
    from conftest import ticket
    from flightscout.search import merge

    normal = ticket(["SAN", "SEA"], dt, price=120.0, source="google").model_copy(update={"seller_kind": "ota"})
    hidden = ticket(["SAN", "SEA"], dt, price=79.0, source="skiplagged").model_copy(
        update={"seller_kind": "ota", "warnings": ["hidden city: don't check bags, final leg must be skipped."]})
    out = merge([normal, hidden])
    assert sorted(i.price for i in out) == [79.0, 120.0]


def test_round_trip_from_prices_keep_their_return_date(monkeypatch, dt):
    from conftest import ticket
    from flightscout import search as s
    from flightscout.models import SearchQuery

    it = ticket(["LAX", "DPS"], dt, price=927.0).model_copy(update={"return_pending": True})
    monkeypatch.setitem(s.SOURCES, "google", lambda q: [it.model_copy()])
    q = SearchQuery(origins=["LAX"], destinations=["DPS"], departure=dt.date(),
                    return_date=dt.date().replace(day=min(dt.day + 1, 28)), sources=["google"])
    res = s.search(q)
    assert res.trips[0].tickets[0].pending_return == q.return_date
