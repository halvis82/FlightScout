"""Metasearch and OTA sources: Wego (plain HTTP), Aviasales (real Chrome),
Omio (real Chrome, off by default). Offline: parsers against small saved
responses. Live (FLIGHTSCOUT_LIVE=1): one real search each."""

import copy
import json
from datetime import date, timedelta

import pytest

from conftest import FIXTURES
from flightscout.models import SearchQuery
from flightscout.sources import _browser, aviasales_browser, omio_browser, wego


def load(name):
    return json.loads((FIXTURES / name).read_text())


def q(o, d, dep, ret=None, **kw):
    return SearchQuery(origins=[o], destinations=[d], departure=date.fromisoformat(dep),
                       return_date=date.fromisoformat(ret) if ret else None, **kw)


# Wego ---------------------------------------------------------------------

def test_wego_parse_cheapest_live_fare_per_trip():
    its = wego.parse(load("wego_dxb_bkk.json"), q("DXB", "BKK", "2026-11-12"), "AED", "https://w")
    assert [i.price for i in its] == [694, 783]  # checked against wego.ae for the same search
    a = its[0]
    assert a.source == "wego" and a.currency == "AED" and a.seller == "Trip.com" and a.seller_kind == "ota"
    s = a.slices[0]
    assert [x.carrier + x.flight_number for x in s.segments] == ["IX926", "IX896"]
    assert s.origin == "DXB" and s.destination == "BKK" and s.stops == 1 and s.duration_min == 710
    assert s.segments[0].carrier_name == "Air India Express"
    assert its[1].seller == "Opodo" and [x.flight_number for x in its[1].slices[0].segments] == ["244", "853"]


def test_wego_drops_cached_fares_other_airports_and_stops():
    data = load("wego_dxb_bkk.json")
    cached = copy.deepcopy(data["fares"][0])
    cached.update(id="x", legsSourceTypes=["NORMAL_CACHE"])
    cached["price"]["totalAmount"] = 1.0
    data["fares"].append(cached)
    its = wego.parse(data, q("DXB", "BKK", "2026-11-12"), "AED", "u")
    assert its[0].price == 694  # the cached 1.0 is not a live quote
    assert wego.parse(data, q("SHJ", "BKK", "2026-11-12"), "AED", "u") == []
    assert wego.parse(data, q("DXB", "BKK", "2026-11-12", max_stops=0), "AED", "u") == []


def test_wego_request_and_links():
    b = wego._body("DXB", "BKK", date(2026, 11, 12), date(2026, 11, 20), 2, "business", "aed")
    s = b["search"]
    assert s["siteCode"] == "AE" and s["currencyCode"] == "AED" and s["adultsCount"] == 2
    assert s["cabin"] == "business" and [x["departureAirportCode"] for x in s["legs"]] == ["DXB", "BKK"]
    assert wego.site_code("LAX") == "US" and wego.site_code("ZZZ") == "US"
    assert wego.search_url("DXB", "BKK", date(2026, 11, 12)).startswith(
        "https://www.wego.com/flights/searches/cDXB-cBKK-2026-11-12/economy/1a:0c:0i")


# Aviasales ----------------------------------------------------------------

def test_aviasales_parse_cheapest_agent_per_ticket():
    its = aviasales_browser.parse(load("aviasales_san_sea.json"), q("SAN", "SEA", "2026-11-13"), "https://a")
    # checked against aviasales.com for the same search: $99 direct 6:00 pm, $110 via OAK / PHX
    assert [i.price for i in its] == [99, 110, 110, 110]
    a = its[0]
    assert a.source == "aviasales" and a.currency == "USD" and a.seller == "Farera" and a.seller_kind == "ota"
    assert a.slices[0].stops == 0 and a.slices[0].segments[0].flight_number == "713"
    assert a.slices[0].segments[0].departure.hour == 18 and a.slices[0].duration_min == 195
    via = its[1].slices[0]
    assert [s.origin for s in via.segments] == ["SAN", "OAK"] and via.destination == "SEA"
    assert via.segments[0].carrier == "WN" and via.duration_min == 410
    assert aviasales_browser.parse(load("aviasales_san_sea.json"), q("SAN", "SEA", "2026-11-13", max_stops=0),
                                   "u")[0].price == 99
    assert aviasales_browser.parse(load("aviasales_san_sea.json"), q("LAX", "SEA", "2026-11-13"), "u") == []


def test_aviasales_links_and_directions():
    assert aviasales_browser.deeplink("SAN", "SEA", date(2026, 11, 13)) == "https://www.aviasales.com/search/SAN1311SEA1"
    assert aviasales_browser.deeplink("LAX", "JFK", date(2026, 11, 6), date(2026, 11, 10), 2) == \
        "https://www.aviasales.com/search/LAX0611JFK10112"
    d = aviasales_browser._directions("LAX", "JFK", date(2026, 11, 6), date(2026, 11, 10))
    assert [x["origin"] for x in d] == ["LAX", "JFK"] and all(x["is_origin_airport"] for x in d)


# Omio ---------------------------------------------------------------------

def test_omio_parse_flights_only_and_merges_duplicates():
    its = omio_browser.parse(load("omio_ber_bcn.json"), q("BER", "BCN", "2026-12-04"), "https://o", "USD")
    assert all(i.source == "omio" and i.seller == "Omio" and i.seller_kind == "ota" for i in its)
    assert [i.slices[0].segments[0].carrier + i.slices[0].segments[0].flight_number for i in its][:2] == \
        ["FR132", "FR148"]  # "FR 148" in the raw data
    assert its[0].price == 52.35
    kl = its[-1].slices[0]
    assert [s.origin for s in kl.segments] == ["BER", "AMS"] and kl.destination == "BCN"
    assert all(len(i.slices[0].segments) >= 1 for i in its)  # the FlixBus card is gone


def test_omio_flight_ids_and_gating(monkeypatch):
    assert omio_browser._flight("FR 148", "Ryanair") == ("FR", "148")
    assert omio_browser._flight("U27174", "easyjet europe") == ("U2", "7174")
    assert omio_browser._flight("7174", "CitizenPlane") == ("??", "7174")
    monkeypatch.setattr(_browser, "available", lambda headful=False: True)
    assert omio_browser.relevant(["BER"], ["BCN"]) and not omio_browser.relevant(["BER"], ["JFK"])
    monkeypatch.delenv("FLIGHTSCOUT_OMIO_UNVERIFIED", raising=False)
    assert omio_browser.search(q("BER", "BCN", "2026-12-04")) == []  # prices not verified yet


# Live ---------------------------------------------------------------------

D = date.today() + timedelta(days=45)


@pytest.mark.live
def test_live_wego():
    its = wego.search(q("DXB", "BKK", str(D), currency="AED"))
    assert its and all(i.source == "wego" and i.price > 0 and i.currency == "AED" for i in its)
    assert all(i.slices[0].origin == "DXB" and i.slices[0].destination == "BKK" for i in its)


@pytest.mark.live
def test_live_aviasales():
    if not _browser.available():
        pytest.skip("needs Playwright + Google Chrome")
    its = aviasales_browser.search(q("SAN", "SEA", str(D)))
    assert its and all(i.source == "aviasales" and i.price > 0 and i.seller for i in its)
    assert all(i.slices[0].origin == "SAN" and i.slices[0].destination == "SEA" for i in its)


@pytest.mark.live
def test_live_omio(monkeypatch):
    if not _browser.available():
        pytest.skip("needs Playwright + Google Chrome")
    monkeypatch.setenv("FLIGHTSCOUT_OMIO_UNVERIFIED", "1")
    its = omio_browser.search(q("BER", "BCN", str(D)))
    assert its and all(i.source == "omio" and i.price > 0 for i in its)
