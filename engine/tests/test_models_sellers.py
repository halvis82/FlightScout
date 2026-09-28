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
    expedia = ticket(["OSL", "SAN"], dt).model_copy(update={"seller": "Expedia", "seller_kind": "ota"})
    google = ticket(["OSL", "SAN"], dt).model_copy(update={"seller": "Google Flights"})
    trips = [Trip(tickets=[expedia], total_price=1, currency="USD"), Trip(tickets=[google], total_price=2, currency="USD")]
    kept = sellers.apply_rules([t.model_copy(deep=True) for t in trips], {"Expedia": "block"})
    assert [t.tickets[0].seller for t in kept] == ["Google Flights"]
    warned = sellers.apply_rules([t.model_copy(deep=True) for t in trips], {"Expedia": "warn"})
    assert any("warning list" in w for w in warned[0].tickets[0].warnings)
    assert not warned[1].tickets[0].warnings


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


def test_flights_without_numbers_stay_apart_in_merge(dt):
    from flightscout.search import merge

    a = ticket(["MAN", "ALC"], dt, source="jet2")
    b = ticket(["MAN", "ALC"], dt.replace(hour=15), source="jet2")
    for it in (a, b):
        for s in it.slices[0].segments:
            s.flight_number = None
    assert len(merge([a, b])) == 2


def test_unreliable_sellers_are_hidden_unless_asked(dt):
    from flightscout.models import Fare, Offer

    def sold_by(name, kind="ota", **kw):
        return ticket(["LAX", "DPS"], dt, source="wego").model_copy(update={"seller": name, "seller_kind": kind, **kw})

    good = sold_by("Expedia")
    priceline = sold_by("Priceline.com")
    bad = [sold_by(n) for n in ("HolidayBreakz", "Mytrip", "EaseMyTrip", "Kiwi.com", "Trip.com", "Gotogate")]
    skiplagged = sold_by("Skiplagged", "metasearch")
    airline = sold_by("Garuda", "airline", offers=[
        Offer(seller="Garuda", is_airline=True, fares=[Fare(price=500)]),
        Offer(seller="Magicfares", is_airline=False, fares=[Fare(price=400)]),
        Offer(seller="Booking.com", is_airline=False, fares=[Fare(price=450)])])
    ita = sold_by("ITA Matrix (book via airline or agency)", "metasearch")
    trips = [Trip(tickets=[x], total_price=x.price, currency="USD")
             for x in [good, priceline, *bad, skiplagged, airline, ita]]
    kept = sellers.apply_rules([t.model_copy(deep=True) for t in trips], None)
    assert [t.tickets[0].seller for t in kept] == ["Expedia", "Priceline.com", "Garuda",
                                                   "ITA Matrix (book via airline or agency)"]
    assert [o.seller for o in kept[2].tickets[0].offers] == ["Garuda", "Booking.com"]  # offers filtered too
    # a split ticket with one unreliable leg is hidden as a whole
    split = Trip(tickets=[good, bad[1]], total_price=1, currency="USD", kind="split")
    assert sellers.apply_rules([split.model_copy(deep=True)], None) == []
    # the old switch (unverified agencies only) doesn't show them any more
    assert len(sellers.apply_rules([t.model_copy(deep=True) for t in trips], {"*unverified": "warn"})) == 4
    shown = sellers.apply_rules([t.model_copy(deep=True) for t in trips], {"*unreliable": "warn"})
    assert len(shown) == len(trips)
    assert all(any("major booking site" in w for w in t.tickets[0].warnings) for t in shown[2:9])
    assert not shown[0].tickets[0].warnings
    assert len(shown[9].tickets[0].offers) == 3
    # a user's block still wins over the checkbox
    assert len(sellers.apply_rules([t.model_copy(deep=True) for t in trips],
                                   {"*unreliable": "warn", "Mytrip": "block"})) == len(trips) - 1


def test_a_cheaper_unreliable_seller_does_not_replace_a_reliable_one_in_merge(dt):
    from flightscout.search import merge

    expedia = ticket(["LAX", "DPS"], dt, price=500.0, source="expedia").model_copy(
        update={"seller": "Expedia", "seller_kind": "ota"})
    mytrip = ticket(["LAX", "DPS"], dt, price=450.0, source="mytrip").model_copy(
        update={"seller": "Mytrip", "seller_kind": "ota"})
    assert sorted(i.seller for i in merge([expedia, mytrip])) == ["Expedia", "Mytrip"]


def test_a_metasearch_result_switches_to_its_cheapest_reliable_seller(dt):
    from flightscout.models import Fare, Offer

    # KAYAK's cheapest is a hidden agency; Expedia sells the same flights 10% higher
    it = ticket(["LAX", "DEL"], dt, price=500.0, source="kayakweb").model_copy(update={
        "seller": "TrustFares", "seller_kind": "ota", "warnings": ["Cheapest of 3 sites on KAYAK: TrustFares."],
        "offers": [Offer(seller="TrustFares", is_airline=False, fares=[Fare(price=400)]),
                   Offer(seller="Expedia", is_airline=False, fares=[Fare(price=440)]),
                   Offer(seller="Mytrip", is_airline=False, fares=[Fare(price=420)])]})
    t = Trip(tickets=[it], total_price=500.0, currency="USD", risks=list(it.warnings))
    kept = sellers.apply_rules([t.model_copy(deep=True)], None)
    tk = kept[0].tickets[0]
    assert (tk.seller, tk.price, kept[0].total_price) == ("Expedia", 550.0, 550.0)
    assert not tk.warnings and not kept[0].risks and [o.seller for o in tk.offers] == ["Expedia"]
    # shown as is when less reliable sellers are included
    shown = sellers.apply_rules([t.model_copy(deep=True)], {"*unreliable": "warn"})
    assert shown[0].tickets[0].seller == "TrustFares" and shown[0].total_price == 500.0
