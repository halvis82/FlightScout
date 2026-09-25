"""OTA and metasearch sources: Booking.com Flights, KAYAK / momondo /
Cheapflights flight search, Trip.com. Offline: parsers against small saved
responses. Live (-m live): one real search each."""

import json
from datetime import date, timedelta

import pytest

from conftest import FIXTURES
from flightscout.models import SearchQuery
from flightscout.sources import _browser, booking, kayakweb, tripcom_browser


def load(name):
    return json.loads((FIXTURES / name).read_text())


def q(o="LAX", d="JFK", dep="2026-11-06", ret=None, **kw):
    return SearchQuery(origins=[o], destinations=[d], departure=date.fromisoformat(dep),
                       return_date=date.fromisoformat(ret) if ret else None, **kw)


# Booking.com

def test_booking_parse():
    its = booking.parse(load("booking_lax_jfk.json"), q(), "LAX", "JFK")
    assert [i.price for i in its] == [224.2, 229.8, 248.4]
    a = its[0]
    assert a.source == "booking" and a.seller == "Booking.com" and a.seller_kind == "ota" and a.currency == "USD"
    assert [s.carrier + s.flight_number for s in a.slices[0].segments] == ["AS668", "AS18"]
    assert a.slices[0].segments[0].carrier_name == "Alaska Airlines"
    assert a.slices[0].segments[0].duration_min == 148  # from the UTC offsets
    assert a.slices[0].duration_min == 556
    assert a.baggage == {"checked": 0, "hand": 1, "hand_types": ["HAND"]}
    assert "/flights/LAX.AIRPORT-JFK.AIRPORT/offer-token-0/?" in a.booking_url
    assert its[2].slices[0].stops == 0 and its[2].slices[0].segments[0].carrier == "B6"


def test_booking_filters_airports_and_stops():
    data = load("booking_lax_jfk.json")
    assert booking.parse(data, q(), "LAX", "EWR") == []  # not the asked airports
    assert [i.price for i in booking.parse(data, q(max_stops=0), "LAX", "JFK")] == [248.4]


def test_booking_params_and_url():
    p = booking._params("OSL", "BCN", date(2026, 11, 6), date(2026, 11, 10), 2, "business", "eur")
    assert p["type"] == "ROUNDTRIP" and p["return"] == "2026-11-10" and p["adults"] == "2"
    assert p["cabinClass"] == "BUSINESS" and p["currency"] == "EUR" and p["from"] == "OSL.AIRPORT"
    u = booking.search_url("OSL", "BCN", date(2026, 11, 6))
    assert u.startswith("https://flights.booking.com/flights/OSL.AIRPORT-BCN.AIRPORT/?type=ONEWAY")


def test_booking_search_dedupes_sorts(monkeypatch):
    calls = []
    monkeypatch.setattr(booking, "_fetch", lambda p: calls.append(p["sort"]) or load("booking_lax_jfk.json"))
    its = booking.search(q())
    assert calls == ["CHEAPEST", "BEST"] and len(its) == 3  # same offers on both pages, merged


# KAYAK family

def test_kayak_parse_cheapest_provider_and_offers():
    its = kayakweb.parse(load("kayak_lax_jfk.json"), q(), "kayakweb", "www.kayak.com", "LAX", "JFK")
    assert len(its) == 2  # the inline ad is skipped
    a, b = its
    assert a.price == 181 and a.seller == "Super.com" and a.seller_kind == "ota" and a.source == "kayakweb"
    assert [s.carrier + s.flight_number for s in a.slices[0].segments] == ["B6188", "B6917"]
    assert a.slices[0].duration_min == 540 and a.slices[0].segments[0].duration_min == 330
    assert {o.seller: o.cheapest for o in a.offers} == {"Super.com": 181, "JetBlue": 184}
    assert a.booking_url == "https://www.kayak.com/flights/LAX-JFK/2026-11-06/f56737f250847e060a16dfdecf1d6e60b?sort=price_a"
    # three sites at $225: the airline itself wins the tie, and its two provider codes are one offer
    assert b.price == 225 and b.seller == "Alaska Airlines" and b.seller_kind == "airline"
    assert sorted(o.seller for o in b.offers) == ["Alaska Airlines", "Expedia", "Orbitz"]
    assert not a.self_transfer


def test_kayak_drops_nearby_airports_and_stops():
    data = load("kayak_lax_jfk.json")
    for s in data["segments"].values():  # pretend KAYAK answered from Ontario
        if s["origin"] == "LAX":
            s["origin"] = "ONT"
    assert kayakweb.parse(data, q(), "kayakweb", "www.kayak.com", "LAX", "JFK") == []
    assert kayakweb.parse(load("kayak_lax_jfk.json"), q(max_stops=0), "kayakweb", "h", "LAX", "JFK") == []


def test_kayak_domains_urls_and_body():
    assert kayakweb.domain("kayakweb", "nok") == ("www.kayak.no", "NOK")
    assert kayakweb.domain("momondo", "EUR") == ("www.momondo.de", "EUR")
    assert kayakweb.domain("cheapflights", "NOK") == ("www.cheapflights.com", "USD")
    u = kayakweb.search_url("momondo", "www.momondo.no", "OSL", "BCN", date(2026, 11, 6), date(2026, 11, 10), 2,
                            "business")
    assert u == "https://www.momondo.no/flight-search/OSL-BCN/2026-11-06/2026-11-10/business/2adults?sort=price_a"
    b = kayakweb._body("LAX", "JFK", date(2026, 11, 6), date(2026, 11, 10), 2, "business", "abc")
    usp = b["userSearchParams"]
    assert usp["searchId"] == "abc" and usp["passengers"] == ["ADT", "ADT"] and len(usp["legs"]) == 2
    assert usp["legs"][1]["origin"]["airports"] == ["JFK"] and usp["legs"][0]["cabinClass"] == "business"
    assert "cabinClass" not in kayakweb._body("LAX", "JFK", date(2026, 11, 6), None, 1, "economy", None)[
        "userSearchParams"]["legs"][0]  # economy is the default, KAYAK rejects an explicit one


# Trip.com

def test_tripcom_parse_stream():
    data = tripcom_browser.events((FIXTURES / "tripcom_lax_jfk.sse").read_text())
    rows = tripcom_browser.parse(data, "LAX", "JFK", 1)
    assert [(r[0], r[1].segments[0].carrier + r[1].segments[0].flight_number) for r in rows] == [
        (243.16, "DL991"), (247.9, "B6524")]
    assert rows[0][1].segments[0].carrier_name == "Delta Air Lines" and rows[0][1].duration_min == 319
    assert tripcom_browser.parse(data, "LAX", "JFK", 2)[0][0] == 486.32  # price is per adult
    assert tripcom_browser.parse(data, "ONT", "JFK", 1) == []


def test_tripcom_search_one_way_and_round_trip(monkeypatch):
    data = tripcom_browser.events((FIXTURES / "tripcom_lax_jfk.sse").read_text())
    monkeypatch.setattr(_browser, "available", lambda headful=False: True)
    urls = []
    monkeypatch.setattr(tripcom_browser, "_fetch", lambda u: urls.append(u) or data)
    its = tripcom_browser.search(q())
    assert [i.price for i in its] == [243.16, 247.9]
    assert its[0].source == "tripcom" and its[0].seller == "Trip.com" and its[0].seller_kind == "ota"
    assert "dcity=lax&acity=nyc&dairport=lax&aairport=jfk&ddate=2026-11-06&triptype=ow" in urls[0]
    rt = tripcom_browser.search(q(ret="2026-11-10"))
    assert rt[0].return_pending and rt[0].trip_type == "roundtrip" and len(rt[0].slices) == 1
    assert "rdate=2026-11-10" in urls[-1] and "triptype=rt" in urls[-1]
    monkeypatch.setattr(_browser, "available", lambda headful=False: False)
    assert tripcom_browser.search(q()) == []


# Live

D = date.today() + timedelta(days=42)


@pytest.mark.live
@pytest.mark.parametrize("fn,src", [(booking.search, "booking"), (kayakweb.search, "kayakweb"),
                                    (kayakweb.search_momondo, "momondo"),
                                    (kayakweb.search_cheapflights, "cheapflights")],
                         ids=["booking", "kayak", "momondo", "cheapflights"])
def test_live_http_ota(fn, src):
    its = fn(q("LAX", "JFK", str(D)))
    assert its, f"{src}: no results"
    assert all(i.source == src and i.price > 0 and i.booking_url.startswith("https://") for i in its)
    assert all(i.slices[0].origin == "LAX" and i.slices[0].destination == "JFK" for i in its)


@pytest.mark.live
def test_live_tripcom():
    if not _browser.available():
        pytest.skip("needs Playwright + Google Chrome")
    its = tripcom_browser.search(q("LAX", "JFK", str(D)))
    assert its and all(i.source == "tripcom" and i.price > 0 for i in its)
    assert all(i.slices[0].origin == "LAX" and i.slices[0].destination == "JFK" for i in its)
