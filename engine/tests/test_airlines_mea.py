"""Direct airline sources for the Middle East, Africa, South Asia and Central
Asia (wave 2b): Biman, FlyArystan, Star Air, Alliance Air, FLY91.
Offline: parsers against saved responses (prices checked on each airline's
own booking page). Live (FLIGHTSCOUT_LIVE=1): one real search per airline,
skipped when the site walls us off or Chrome is missing."""

import json
from datetime import date, timedelta

import pytest

from conftest import FIXTURES
from flightscout.models import SearchQuery
from flightscout.sources import _browser, _c_crane, allianceair, biman, fly91_browser, flyarystan, starair
from flightscout.sources._airline import combine


def _load(name):
    return json.loads((FIXTURES / name).read_text())


def _text(name):
    return (FIXTURES / name).read_text()


def _q(o, d, dep, ret=None, **kw):
    return SearchQuery(origins=[o], destinations=[d], departure=date.fromisoformat(dep),
                       return_date=date.fromisoformat(ret) if ret else None, **kw)


def _soon(days=40):
    return (date.today() + timedelta(days=days)).isoformat()


# ---- Biman (Sabre DX GraphQL) ---------------------------------------------

def test_biman_parse_round_trip():
    # DAC-DXB 5 to 12 Nov 2026, 2 adults. booking.biman-airlines.com showed
    # BG 147 at 41,004 BDT and BG 148 at 35,461 BDT per person; after picking
    # both, "Trip Total" was 152,930 BDT = 2 x (41,004 + 35,461).
    bounds, cur = biman.parse(_load("biman_dac_dxb_rt.json"), adults=2)
    assert cur == "BDT" and len(bounds) == 2
    (out,), (back,) = bounds  # sold out flights are left out
    assert out["total"] == 82008 and out["fare"] == "EV" and back["total"] == 70922
    s = out["segments"][0]
    assert (s["carrier"], s["number"], s["origin"], s["destination"]) == ("BG", "147", "DAC", "DXB")
    assert s["departure"] == "2026-11-05T18:35:00+06:00" and s["arrival"] == "2026-11-06T00:30:00+04:00"
    its = combine(_q("DAC", "DXB", "2026-11-05", "2026-11-12", adults=2), "biman", "Biman", [out], [back], cur,
                  "https://x", biman.NAMES)
    assert its[0].price == 152930 and its[0].slices[0].duration_min == 475
    biz, _ = biman.parse(_load("biman_dac_dxb_rt.json"), adults=2, cabin="business")
    assert biz[0][0]["total"] > out["total"]


def test_biman_relevance_and_deeplink():
    assert biman.relevant(["DAC"], ["DXB"])
    assert biman.relevant(["CGP"], ["JED"])
    assert not biman.relevant(["LHR"], ["DXB"])  # Dhaka is far off the way
    assert not biman.relevant(["JFK"], ["LHR"])
    url = biman.deeplink("DAC", "DXB", date(2026, 11, 5), date(2026, 11, 12), 2)
    assert "journeyType=round-trip" in url and "ADT=2" in url and "date=11-05-2026" in url
    assert "origin1=DXB&destination1=DAC&date1=11-12-2026" in url


# ---- Hitit Crane: FlyArystan, Star Air --------------------------------------

def test_flyarystan_parse_round_trip():
    # ALA-NQZ 5 to 10 Nov 2026, 2 adults: "LOWEST" 26,172 KZT per person on
    # booking.flyarystan.com, TOTAL 52,344 after picking the bundle.
    res = _c_crane.parse(_text("flyarystan_ala_nqz_rt.html"), 2, "economy", "ALA", "NQZ")
    outs, backs = res["OUTBOUND"], res["INBOUND"]
    assert len(outs) == 7 and len(backs) == 5  # nonstop only (3 connections left out)
    first = outs[0]
    assert first["total"] == 52344 and first["currency"] == "KZT" and first["fare"] == "PROMO"
    s = first["segments"][0]
    assert (s["carrier"], s["number"], s["origin"], s["destination"]) == ("FS", "7051", "ALA", "NQZ")
    assert s["departure"] == "2026-11-05T06:30:00" and s["arrival"] == "2026-11-05T08:30:00" and s["duration"] == 120
    assert backs[0]["segments"][0]["origin"] == "NQZ" and backs[0]["total"] == 46850
    assert _c_crane.parse(_text("flyarystan_ala_nqz_rt.html"), 2, "business", "ALA", "NQZ")["OUTBOUND"] == []


def test_starair_parse_cabins():
    # BLR-GBI 6 to 9 Nov 2026: STAR REGULAR INR 4,500 per person (2 adults:
    # cart TOTAL PRICE INR 9,000 on book-sdg.crane.aero), Business 9,500.
    html = _text("starair_blr_gbi_rt.html")
    eco = _c_crane.parse(html, 2, "economy", "BLR", "GBI")
    assert [(j["segments"][0]["number"], j["total"]) for j in eco["OUTBOUND"]] == [("117", 9000)]
    assert eco["OUTBOUND"][0]["segments"][0]["carrier"] == "S5" and eco["OUTBOUND"][0]["currency"] == "INR"
    assert eco["INBOUND"][0]["segments"][0]["origin"] == "GBI" and eco["INBOUND"][0]["total"] == 11000
    biz = _c_crane.parse(html, 1, "business", "BLR", "GBI")
    assert biz["OUTBOUND"][0]["total"] == 9500 and biz["OUTBOUND"][0]["fare"] == "BUSINESS"


def test_crane_helpers():
    assert _c_crane._num("26 172") == 26172 and _c_crane._num("4,500") == 4500
    assert _c_crane._num("1,234.50") == 1234.5 and _c_crane._num("12,5") == 12.5
    assert _c_crane._day("05.11.2026") == date(2026, 11, 5) and _c_crane._day("06 Nov 2026") == date(2026, 11, 6)
    assert _c_crane._cabin_of("PROMO") == "economy" and _c_crane._cabin_of("BUSINESS") == "business"
    assert _c_crane._cabin_of("executive_economy") == "premium"
    assert _c_crane.parse("<html>no flights</html>") == {"OUTBOUND": [], "INBOUND": []}


def test_crane_relevance_and_deeplinks(monkeypatch):
    monkeypatch.setattr(flyarystan, "ports", lambda: {"ALA", "NQZ", "IST", "DXB"})
    monkeypatch.setattr(starair, "ports", lambda: {"BLR", "GBI", "BOM", "BAH"})
    assert flyarystan.relevant(["ALA"], ["NQZ"]) and flyarystan.relevant(["NQZ"], ["IST"])
    assert not flyarystan.relevant(["IST"], ["DXB"])  # neither end in Kazakhstan
    assert starair.relevant(["BLR"], ["GBI"]) and not starair.relevant(["BLR"], ["DEL"])
    url = flyarystan.deeplink("ALA", "NQZ", date(2026, 11, 5), date(2026, 11, 10), 2)
    assert url.startswith("https://booking.flyarystan.com/ibe/availability?depPort=ALA&arrPort=NQZ")
    assert "departureDate=05.11.2026" in url and "tripType=ROUND_TRIP" in url and "returnDate=10.11.2026" in url
    assert "adult=2" in starair.deeplink("BLR", "GBI", date(2026, 11, 6), adults=2)


# ---- Alliance Air ------------------------------------------------------------

def test_allianceair_parse_round_trip():
    # BLR-COK 5 to 12 Nov 2026, 2 adults: bookme.allianceair.in showed 9I507
    # INR 4,654 per person, 9,308 selected, 9I508 back 9,534, Total Cost 18,842.
    outs, backs = allianceair.parse(_load("allianceair_blr_cok_rt.json"))
    assert [(j["segments"][0]["number"], j["total"], j["fare"]) for j in outs] == [("507", 9308, "SUPSAV")]
    assert [(j["segments"][0]["number"], j["total"]) for j in backs] == [("508", 9534)]
    s = outs[0]["segments"][0]
    assert (s["carrier"], s["origin"], s["destination"], s["departure"]) == ("9I", "BLR", "COK", "2026-11-05T07:05:00")
    its = combine(_q("BLR", "COK", "2026-11-05", "2026-11-12", adults=2), "allianceair", "Alliance Air", outs,
                  backs, "INR", "https://x", allianceair.NAMES)
    assert its[0].price == 18842 and its[0].slices[0].duration_min == 95


def test_allianceair_routes_and_schedule():
    html = ('<script>var _orgDesList = [{"origin":"BLR","destination":"COK"},{"origin":"BLR","destination":"HYD"},'
            '{"origin":"COK","destination":"BLR"}];</script>'
            '<script>this.dataSchedule = ["", {"success": true, "departure_schedule": []}, ""];</script>')
    assert allianceair.routes_from(html) == {"BLR": ["COK", "HYD"], "COK": ["BLR"]}
    assert allianceair.schedule(html)["success"] is True
    with pytest.raises(RuntimeError):
        allianceair.schedule("<html>maintenance</html>")


# ---- FLY91 (IBS iFly Res) ------------------------------------------------------

def test_fly91_parse():
    # GOX-HYD 5 Nov 2026, 2 adults. The list shows fares per person without
    # the convenience fee; picking IC 5303 showed Total 8,994 INR = 2 x 4,199
    # + 2 x 298, picking IC 5202/5203 Total 12,150.
    fl = fly91_browser.parse(_text("fly91_gox_hyd.html"))
    assert [([s["number"] for s in f["segments"]], f["fare_pp"], f["radio"]) for f in fl] == [
        (["5202", "5203"], 5777, "flight-0-0-0"), (["5303"], 4199, "flight-0-2-0")]
    conn = fl[0]["segments"]
    assert (conn[0]["origin"], conn[0]["destination"], conn[1]["destination"]) == ("GOX", "JLG", "HYD")
    assert conn[1]["departure"] == "2026-11-06T18:00:00+05:30" and conn[0]["duration"] == 115
    its = combine(_q("SDW", "HYD", "2026-11-05", adults=2), "fly91", "FLY91", [{**fl[1], "total": 8994}], None,
                  "INR", "https://x", fly91_browser.NAMES)
    assert its[0].price == 8994 and its[0].slices[0].segments[0].carrier == "IC"


def test_fly91_relevance_and_deeplink(monkeypatch):
    monkeypatch.setattr(_browser, "available", lambda headful=False: True)
    assert fly91_browser.relevant(["GOX"], ["HYD"]) and not fly91_browser.relevant(["DEL"], ["HYD"])
    url = fly91_browser.deeplink("GOX", "HYD", date(2026, 11, 5), 2)
    assert "origin=GOX&destination=HYD&travelDate=05-Nov-2026&adults=2" in url
    monkeypatch.setattr(_browser, "available", lambda headful=False: False)
    assert not fly91_browser.relevant(["GOX"], ["HYD"])


# ---- live ------------------------------------------------------------------------

def _live(fn):
    try:
        return fn()
    except Exception as e:  # walled off or the site is down: not a parsing failure
        pytest.skip(f"blocked or unavailable: {e}")


@pytest.mark.live
def test_live_biman():
    its = _live(lambda: biman.search(_q("DAC", "DXB", _soon())))
    assert its and its[0].currency == "BDT" and its[0].slices[0].segments[0].carrier == "BG"


@pytest.mark.live
def test_live_flyarystan():
    its = _live(lambda: flyarystan.search(_q("ALA", "NQZ", _soon(), _soon(45))))
    assert its and its[0].source == "flyarystan" and len(its[0].slices) == 2


@pytest.mark.live
def test_live_starair():
    its = _live(lambda: starair.search(_q("BLR", "GBI", _soon())))
    if not its:
        pytest.skip("no Star Air flight that day")
    assert its[0].currency == "INR" and its[0].slices[0].segments[0].carrier == "S5"


@pytest.mark.live
def test_live_allianceair():
    its = _live(lambda: allianceair.search(_q("BLR", "COK", _soon())))
    if not its:
        pytest.skip("no Alliance Air flight that day")
    assert its[0].currency == "INR" and its[0].slices[0].segments[0].carrier == "9I"


@pytest.mark.live
def test_live_fly91():
    if not _browser.available():
        pytest.skip("needs Chrome and Playwright")
    its = _live(lambda: fly91_browser.search(_q("GOX", "HYD", _soon())))
    if not its:
        pytest.skip("no FLY91 flight that day")
    assert its[0].currency == "INR" and its[0].slices[0].segments[0].carrier == "IC"
