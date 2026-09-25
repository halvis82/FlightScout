"""Expedia Group (Expedia, Orbitz, Travelocity) flight search. Offline: the
parser against a trimmed GraphQL answer. Live (-m live): one real search per
brand over plain HTTP."""

import json
from datetime import date, timedelta

import pytest

from conftest import FIXTURES
from flightscout.models import SearchQuery
from flightscout.sources import expedia

FX = json.loads((FIXTURES / "expedia_lax_jfk.json").read_text())
DEP = date(2026, 11, 6)


def q(o="LAX", d="JFK", dep=DEP, ret=None, **kw):
    return SearchQuery(origins=[o], destinations=[d], departure=dep, return_date=ret, **kw)


def test_parse_one_way():
    js = expedia.parse(FX["oneway_lax_jfk_2026-11-06_1adt"], DEP)
    assert len(js) == 3
    j = js[0]
    assert j["total"] == 224.2 and j["duration"] == 556  # "$224.20 one way for 1 traveler", 9h 16m
    assert [(s["carrier"], s["number"], s["origin"], s["destination"]) for s in j["segments"]] == [
        ("AS", "668", "LAX", "PDX"), ("AS", "18", "PDX", "JFK")]
    assert j["segments"][0]["departure"] == "2026-11-06T07:03:00"
    assert j["segments"][1]["arrival"] == "2026-11-06T19:19:00" and j["segments"][1]["duration"] == 329
    assert [f["name"] for f in j["fares"]] == ["Saver", "Main", "Refundable Main"]
    # an overnight arrival lands on the next day
    assert js[2]["segments"][1]["arrival"] == "2026-11-07T07:25:00"


def test_itineraries_one_way():
    js = expedia.parse(FX["oneway_lax_jfk_2026-11-06_1adt"], DEP)
    its = expedia.itineraries("orbitz", q(), js, "USD", "https://www.orbitz.com/x")
    assert len(its) == 3
    i = its[0]
    assert i.source == "orbitz" and i.seller == "Orbitz" and i.seller_kind == "ota"
    assert i.price == 224.2 and i.currency == "USD" and not i.return_pending and i.trip_type == "oneway"
    assert i.slices[0].stops == 1 and i.flight_key.startswith("AS668@20261106")
    assert i.offers[0].cheapest == 224.2
    assert expedia.itineraries("expedia", q(max_stops=0), js, "USD", "u") == []
    assert expedia.itineraries("expedia", q(o="BUR"), js, "USD", "u") == []  # exact airports only


def test_round_trip_is_return_pending_total_for_all_travelers():
    js = expedia.parse(FX["roundtrip_lax_jfk_2026-11-06_2026-11-10_2adt"], DEP)
    assert js[0]["total"] == 835.6  # "$835.60 roundtrip for 2 travelers"
    its = expedia.itineraries("expedia", q(ret=date(2026, 11, 10), adults=2), js, "USD", "u")
    assert its[0].return_pending and its[0].trip_type == "roundtrip" and len(its[0].slices) == 1
    assert its[0].slices[0].segments[0].flight_number == "4" and its[0].price == 835.6


def test_amount_and_time_parsing():
    assert expedia._amount("$1,063.20 roundtrip for 2 travelers") == 1063.2
    assert expedia._amount("£34 one way for 1 traveller") == 34
    assert expedia._amount("€1.234,50") == 1234.5
    assert expedia._minutes("Travel time: 5h 29m") == 329 and expedia._minutes("45m") == 45
    assert expedia._when([{"text": "12:05am"}, {"text": "Sat, Nov 7"}], DEP).isoformat() == "2026-11-07T00:05:00"
    assert expedia._when([{"text": "20:50"}, {"text": "Fri, 13 Nov"}], DEP).isoformat() == "2026-11-13T20:50:00"
    assert expedia._when([{"text": "9:10am"}, {"text": "Sat, Jan 2"}], date(2026, 12, 31)).year == 2027


def test_domains_and_deeplink():
    assert expedia.domain("expedia", "GBP") == "www.expedia.co.uk"
    assert expedia.domain("expedia", "NOK") == "www.expedia.com"  # non English sites: USD, converted later
    assert expedia.domain("travelocity", "EUR") == "www.travelocity.com"
    u = expedia.deeplink("www.orbitz.com", "LAX", "JFK", DEP, date(2026, 11, 10), 2)
    assert u.startswith("https://www.orbitz.com/Flights-Search?trip=roundtrip&leg1=from:LAX,to:JFK,departure:11/6/2026TANYT")
    assert "leg2=from:JFK,to:LAX,departure:11/10/2026TANYT" in u and "passengers=adults:2" in u


@pytest.mark.live
@pytest.mark.parametrize("brand", ["expedia", "orbitz", "travelocity"])
def test_live_expedia_group(brand):
    dep = date.today() + timedelta(days=42)
    its = expedia.search_brand(brand, q("LAX", "JFK", dep))
    assert its, f"{brand}: no results"
    assert all(i.source == brand and i.seller_kind == "ota" and i.price > 0 and i.currency == "USD" for i in its)
    assert all(i.slices[0].origin == "LAX" and i.slices[0].destination == "JFK" for i in its)
    assert all(i.booking_url.startswith("https://") for i in its)
