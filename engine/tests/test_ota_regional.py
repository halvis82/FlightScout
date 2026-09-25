"""Etraveli (Gotogate, Mytrip), eDreams ODIGEO (eDreams, Opodo) and regional
OTAs (Almosafer, Traveloka, Cleartrip). Offline: parsers against small saved
responses. Live (FLIGHTSCOUT_LIVE=1): one real search per site."""

import json
from datetime import date, timedelta

import pytest

from conftest import FIXTURES
from flightscout.models import SearchQuery
from flightscout.sources import (_browser, almosafer, cleartrip, edreams, gotogate, mytrip, opodo,  # noqa: F401
                                 traveloka)


def load(name):
    return json.loads((FIXTURES / name).read_text())


def q(o, d, dep="2026-11-06", ret=None, **kw):
    return SearchQuery(origins=[o], destinations=[d], departure=date.fromisoformat(dep),
                       return_date=date.fromisoformat(ret) if ret else None, **kw)


def keys(it):
    return [f"{s.carrier}{s.flight_number}" for sl in it.slices for s in sl.segments]


def test_gotogate_parse_prices_and_self_transfer():
    its = gotogate.parse(load("gotogate_bcn_lhr.json"), "gotogate")
    by = {tuple(keys(i)): i for i in its}
    fr = by[("FR774", "FR467")]
    assert fr.price == 37.99 and fr.currency == "GBP" and fr.self_transfer  # minor units -> 37.99
    assert fr.slices[0].destination == "STN" and fr.slices[0].duration_min == 590
    assert fr.seller == "Gotogate" and fr.seller_kind == "ota" and fr.source == "gotogate"
    vy = by[("VY7642",)]
    assert vy.price == 46.38 and not vy.self_transfer and vy.slices[0].segments[0].carrier == "VY"
    assert vy.booking_url.startswith("https://uk.gotogate.com/from/sharedurl/air/BCNLHR06NOV")
    assert mytrip.search is not gotogate.search
    assert gotogate.parse(load("gotogate_bcn_lhr.json"), "mytrip")[0].seller == "Mytrip"


def test_gotogate_domains_and_airport_filter(monkeypatch):
    assert gotogate.domain("gotogate", "GBP") == "uk.gotogate.com"
    assert gotogate.domain("mytrip", "JPY") == "www.mytrip.com"  # unknown currency: USD site
    calls = []
    monkeypatch.setattr(gotogate, "_post", lambda host, v: calls.append((host, v)) or load("gotogate_bcn_lhr.json"))
    its = gotogate.search(q("BCN", "LHR", currency="GBP"))
    assert [keys(i) for i in its] == [["VY7642"]]  # the Stansted trip is dropped
    assert {c[0] for c in calls} == {"uk.gotogate.com"} and len(calls) == 3
    assert calls[0][1]["routes"] == [{"origin": "BCN", "destination": "LHR", "departureDate": "2026-11-06"}]
    calls.clear()
    gotogate.search(q("BCN", "LHR", max_stops=0))
    assert len(calls) == 1 and calls[0][1]["direct"] is True


def test_opodo_parse_regular_price_and_prime_warning():
    its = edreams.parse(load("opodo_bcn_lhr.json"), "opodo", adults=1, url="u")
    by = {tuple(keys(i)): i for i in its}
    vy = by[("VY7642",)]
    assert vy.price == 59.97 and vy.currency == "GBP" and vy.seller == "Opodo" and vy.source == "opodo"
    assert any("36.97" in w for w in vy.warnings)  # the Prime price is only mentioned
    assert by[("BA475",)].price == 75.97
    assert by[("VY1302", "U22316")].slices[0].stops == 1
    two = edreams.parse(load("opodo_bcn_lhr.json"), "opodo", adults=2)
    assert {tuple(keys(i)): i.price for i in two}[("VY7642",)] == 119.94  # fees are per passenger


def test_edreams_deeplink_and_filter(monkeypatch):
    u = edreams.deeplink("www.edreams.com", "MAD", "CDG", date(2026, 11, 6), date(2026, 11, 10), 2)
    assert u == ("https://www.edreams.com/travel/#results/type=R;dep=2026-11-06;ret=2026-11-10;from=MAD;to=CDG;"
                 "adults=2;collectionmethod=false;airlinescodes=false;internalSearch=true")
    monkeypatch.setattr(_browser, "available", lambda headful=False: True)
    monkeypatch.setattr(edreams, "_fetch", lambda brand, url: load("opodo_bcn_lhr.json"))
    its = opodo.search(q("BCN", "LHR", currency="GBP"))
    assert [keys(i) for i in its][:2] == [["VY7642"], ["BA475"]]  # Gatwick trip dropped, cheapest first
    assert its[0].booking_url.startswith("https://www.opodo.co.uk/travel/#results/type=O;dep=2026-11-06;from=BCN")
    assert opodo.search(q("BCN", "LHR", max_stops=0)) and all(
        i.slices[0].stops == 0 for i in opodo.search(q("BCN", "LHR", max_stops=0)))


def test_almosafer_parse_and_filter(monkeypatch):
    its = almosafer.parse(load("almosafer_dxb_ruh.json"), "u")
    by = {tuple(keys(i)): i for i in its}
    assert by[("XY210",)].price == 66.41 and by[("XY210",)].currency == "USD"
    assert by[("F3512",)].price == 74.4 and by[("F3512",)].seller == "Almosafer"
    assert by[("G9151",)].slices[0].origin == "SHJ"
    assert any(len(k) == 2 for k in by)
    monkeypatch.setattr(_browser, "available", lambda headful=False: True)
    monkeypatch.setattr(almosafer, "_fetch", lambda url: load("almosafer_dxb_ruh.json"))
    got = almosafer.search(q("DXB", "RUH"))
    assert got and all(i.slices[0].origin == "DXB" for i in got)  # Sharjah dropped
    assert almosafer.search(q("DXB", "RUH", ret="2026-11-10")) == []  # one way only
    assert almosafer.deeplink("DXB", "RUH", date(2026, 11, 6), 2).endswith("/DXB-RUH/2026-11-06/Economy/2Adult")


def test_traveloka_parse(monkeypatch):
    its = traveloka.parse(load("traveloka_cgk_dps.json"), adults=1, url="u")
    by = {tuple(keys(i)): i for i in its}
    assert by[("8B5108",)].price == 1442765 and by[("8B5108",)].currency == "IDR"
    assert by[("QZ818",)].price == 1452300 and by[("JT12",)].price == 1578400
    conn = next(i for k, i in by.items() if len(k) == 2)
    assert conn.slices[0].segments[0].destination == "KUL"
    assert traveloka.parse(load("traveloka_cgk_dps.json"), adults=2)[0].price in {2 * i.price for i in its}
    assert "ap=CGK.DPS&dt=06-11-2026.NA&ps=1.0.0" in traveloka.deeplink("CGK", "DPS", date(2026, 11, 6))


def test_cleartrip_parse_and_filter(monkeypatch):
    its = cleartrip.parse(load("cleartrip_bom_del.json"), "u")
    by = {tuple(keys(i)): i for i in its}
    assert by[("SG613",)].price == 11984 and by[("SG511",)].price == 11984 and by[("SG611",)].price == 12960
    assert by[("SG613",)].currency == "INR" and by[("SG613",)].slices[0].departure.hour == 21
    monkeypatch.setattr(_browser, "available", lambda headful=False: True)
    monkeypatch.setattr(cleartrip, "_fetch", lambda url: load("cleartrip_bom_del.json"))
    got = cleartrip.search(q("BOM", "DEL"))
    assert got[0].price == 11984 and all(i.slices[0].origin == "BOM" for i in got)  # Navi Mumbai dropped
    assert len(cleartrip.search(q("BOM", "DEL", max_stops=0))) == 3
    assert "intl=n" in cleartrip.deeplink("BOM", "DEL", date(2026, 11, 6))
    assert "intl=y" in cleartrip.deeplink("BOM", "DXB", date(2026, 11, 6))


D = date.today() + timedelta(days=42)
LIVE = [
    ("gotogate", gotogate, "BCN", "LHR", "GBP", False),
    ("mytrip", mytrip, "BCN", "LHR", "GBP", False),
    ("edreams", edreams, "MAD", "CDG", "EUR", True),
    ("opodo", opodo, "BCN", "LHR", "GBP", True),
    ("almosafer", almosafer, "DXB", "RUH", "USD", True),
    ("traveloka", traveloka, "CGK", "DPS", "IDR", True),
    ("cleartrip", cleartrip, "BOM", "DEL", "INR", True),
]


@pytest.mark.live
@pytest.mark.parametrize("name,mod,o,d,cur,browser", LIVE, ids=[x[0] for x in LIVE])
def test_live_regional_ota(name, mod, o, d, cur, browser):
    if browser and not _browser.available():
        pytest.skip("needs Playwright + Google Chrome")
    its = mod.search(q(o, d, str(D), currency=cur))
    assert its, f"{name}: no results for {o}-{d} on {D}"
    assert all(i.source == name and i.seller_kind == "ota" and i.price > 0 for i in its)
    assert all(i.booking_url.startswith("https://") for i in its)
    assert all(i.slices[0].origin == o and i.slices[0].destination == d for i in its)
    assert all(i.slices[0].departure.date() == D for i in its)
