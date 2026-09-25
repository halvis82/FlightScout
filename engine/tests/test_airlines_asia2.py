"""Direct airline sources for East and Southeast Asia and Oceania (wave 2a).
Offline: parsers against saved responses. Live (FLIGHTSCOUT_LIVE=1): one real
search per airline, skipped when the site blocks us or Chrome is missing."""

import json
from datetime import date, timedelta

import pytest

from conftest import FIXTURES
from flightscout.models import SearchQuery
from flightscout.sources import (_browser, _c_ezycommerce, _des, airniugini_browser, bangkokair_browser,
                                 linkairways_browser, nokair, philippineairlines_browser, spring,
                                 vietnamairlines_browser)
from flightscout.sources._airline import combine

_BLOCKED = ("403", "429", "forbidden", "just a moment", "access denied", "captcha", "blocked", "cloudflare",
            "akamai", "timeout", "timed out")


def _load(name):
    return json.loads((FIXTURES / name).read_text())


def _q(o, d, dep, ret=None, **kw):
    return SearchQuery(origins=[o] if isinstance(o, str) else o, destinations=[d] if isinstance(d, str) else d,
                       departure=date.fromisoformat(dep) if isinstance(dep, str) else dep,
                       return_date=(date.fromisoformat(ret) if isinstance(ret, str) else ret) if ret else None, **kw)


def _future(days=35):
    return date.today() + timedelta(days=days)


def _live(fn):
    """Run a live search; a block (bot wall, rate limit, timeout) skips."""
    try:
        return fn()
    except Exception as e:
        if any(k in str(e).lower() for k in _BLOCKED) or isinstance(e, TimeoutError):
            pytest.skip(f"blocked: {str(e)[:120]}")
        raise


# --- Nok Air (EzyCommerce) ---------------------------------------------------

def test_nokair_parse():
    data = _load("nokair_dmk_cnx.json")
    js = nokair._nonstop(_c_ezycommerce.parse(data, 0, "economy", date(2026, 10, 22)))
    # matched booking.nokair.com: DD120 2,455.00 and DD124 2,755.00 (NOK LITE)
    assert [(j["segments"][0]["number"], j["total"], j["fare"]) for j in js] == [
        ("120", 2455.0, "NOK LITE"), ("124", 2755.0, "NOK LITE")]
    assert js[0]["segments"][0]["departure"].startswith("2026-10-22T06:30")
    its = combine(_q("DMK", "CNX", "2026-10-22", adults=1), "nokair", "Nok Air", js, None, "THB", "https://x",
                  nokair.NAMES)
    assert its[0].price == 2455.0 and its[0].seller_kind == "airline"


def test_nokair_relevance_and_deeplink(monkeypatch):
    monkeypatch.setattr(nokair.EZY, "network", lambda: {"DMK": ["CNX", "HKT", "AM1"], "CNX": ["DMK"]})
    assert nokair.relevant(["DMK"], ["CNX"])
    assert not nokair.relevant(["DMK"], ["AM1"])  # bus / van transfer point
    assert not nokair.relevant(["DMK"], ["NRT"])
    monkeypatch.setattr(nokair.EZY, "network", lambda: None)  # list down: Thailand gate
    assert nokair.relevant(["BKK"], ["NRT"]) and not nokair.relevant(["OSL"], ["CDG"])
    u = nokair.deeplink("DMK", "CNX", date(2026, 10, 22), date(2026, 10, 25), 2)
    assert u.startswith("https://booking.nokair.com/?routes[0][from]=DMK")
    assert "routes[1][from]=CNX" in u and "passengers[0][count]=2" in u and "currency=THB" in u


@pytest.mark.live
def test_nokair_live():
    its = _live(lambda: nokair.search(_q("DMK", "CNX", _future())))
    assert its and its[0].currency == "THB" and its[0].slices[0].segments[0].carrier == "DD"


# --- Spring Airlines -----------------------------------------------------------

def test_spring_parse():
    data = _load("spring_pvg_kix.json")
    js = spring.parse(data, adults=2, day=date(2026, 10, 22))
    # matched en.ch.com: 9C6575 CNY 1,002 per adult incl. CNY 402 taxes
    assert [(j["segments"][0]["number"], j["total"]) for j in js] == [("6575", 2004.0), ("6565", 2404.0),
                                                                         ("6581", 2004.0)]
    s = js[0]["segments"][0]
    assert (s["origin"], s["destination"], s["carrier"]) == ("PVG", "KIX", "9C")
    assert s["departure"] == "2026-10-22T08:05:00" and s["arrival"] == "2026-10-22T11:20:00"
    assert s["duration"] == 135
    assert spring.parse(data, day=date(2026, 10, 23)) == []


def test_spring_relevance_and_deeplink():
    assert spring.relevant(["PVG"], ["KIX"]) and spring.relevant(["NRT"], ["SHA"])
    assert spring.relevant(["SHA"], ["SZX"])
    assert not spring.relevant(["NRT"], ["ICN"])  # no China end
    assert not spring.relevant(["PVG"], ["LHR"])
    assert spring.city("PVG") == "SHA" and spring.city("KIX") == "OSA" and spring.city("CAN") == "CAN"
    u = spring.deeplink("PVG", "KIX", date(2026, 10, 22), date(2026, 10, 27), 2)
    assert u.startswith("https://en.ch.com/flights/SHA-OSA.html?FDate=2026-10-22&RetDate=2026-10-27&ANum=2")
    assert "IfRet=true" in u


def test_spring_bound_filters_airports(monkeypatch):
    data = _load("spring_pvg_kix.json")
    monkeypatch.setattr(spring, "_fetch", lambda o, d, day, adults: data)
    assert len(spring._bound(["PVG"], ["KIX"], date(2026, 10, 22), 1)) == 3
    assert spring._bound(["SHA"], ["KIX"], date(2026, 10, 22), 1) == []  # all leave from Pudong


@pytest.mark.live
def test_spring_live():
    its = _live(lambda: spring.search(_q(["PVG", "SHA"], ["KIX"], _future())))
    assert its and its[0].currency == "CNY" and its[0].slices[0].segments[0].carrier == "9C"


# --- Link Airways ----------------------------------------------------------------

def test_linkairways_parse_round_trip():
    data = _load("linkairways_bne_arm_rt.json")
    outs = linkairways_browser.parse(data["OB"], "BNE", "ARM", adults=2)
    backs = linkairways_browser.parse(data["IB"], "ARM", "BNE", adults=2)
    # matched search.linkairways.com: "AUD 315.00" Deal per adult, summary "Total Price AUD 630.00" for 2
    assert [(j["segments"][0]["number"], j["total"], j["fare"]) for j in outs] == [("883", 630.0, "Deal")]
    s = outs[0]["segments"][0]
    assert s["departure"] == "2026-10-22T08:45:00" and s["arrival"] == "2026-10-22T10:55:00"
    assert s["duration"] == 70 and s["carrier"] == "FC"
    assert backs[0]["segments"][0]["number"] == "884"
    its = combine(_q("BNE", "ARM", "2026-10-22", "2026-10-27", adults=2), "linkairways", "Link Airways", outs,
                  backs, "AUD", "https://x", linkairways_browser.NAMES)
    assert its[0].price == 1260.0 and its[0].trip_type == "roundtrip"


def test_linkairways_relevance_and_deeplink(monkeypatch):
    monkeypatch.setattr(_browser, "available", lambda headful=False: True)
    assert linkairways_browser.relevant(["BNE"], ["ARM"])
    assert not linkairways_browser.relevant(["SYD"], ["ARM"])
    monkeypatch.setattr(_browser, "available", lambda headful=False: False)
    assert not linkairways_browser.relevant(["BNE"], ["ARM"])
    u = linkairways_browser.deeplink("BNE", "ARM", date(2026, 10, 22), date(2026, 10, 27), 2)
    assert "Jtype=2&depCity=BNE&arrCity=ARM&depDate=22/10/2026&arrDate=27/10/2026&adult1=2" in u


@pytest.mark.live
def test_linkairways_live():
    if not _browser.available():
        pytest.skip("needs Chrome and Playwright")
    its = _live(lambda: linkairways_browser.search(_q("BNE", "ARM", _future())))
    if not its:
        pytest.skip("no Link Airways flight that day")
    assert its[0].currency == "AUD" and its[0].slices[0].segments[0].carrier == "FC"


# --- Amadeus DES airlines (Bangkok Airways, Vietnam Airlines, PAL) -------------

def test_des_search_fields():
    f = dict(_des.search_fields("BKK", "USM", date(2026, 10, 22), 2, ["PGREFXFLEX"], [{"key": "a", "value": 1}]))
    s = json.loads(f["search"])
    assert s["travelers"] == [{"passengerTypeCode": "ADT"}] * 2 and s["commercialFareFamilies"] == ["PGREFXFLEX"]
    assert s["itineraries"] == [{"originLocationCode": "BKK", "destinationLocationCode": "USM",
                                 "departureDateTime": "2026-10-22T00:00:00.000"}]
    assert json.loads(f["portalFacts"]) == [{"key": "a", "value": 1}]
    assert "portalFacts" not in dict(_des.search_fields("SGN", "HAN", date(2026, 10, 22), 1, None, None))


def test_bangkokair_parse():
    js, cur = _des.parse(_load("bangkokair_bkk_usm.json"))
    by = {j["segments"][0]["number"]: j for j in js}
    # matched digital.bangkokair.com: PG171 "Economy from THB 4,180", PG121 THB 4,480
    assert cur == "THB" and by["171"]["total"] == 4180.0 and by["121"]["total"] == 4480.0
    assert by["171"]["fare"] == "PGPROMO" and by["171"]["segments"][0]["departure"].startswith("2026-10-22T15:45")
    biz, _ = _des.parse(_load("bangkokair_bkk_usm.json"), "business")
    assert biz and all(b["total"] > 4180 for b in biz)


def test_bangkokair_relevance(monkeypatch):
    monkeypatch.setattr(_browser, "available", lambda headful=False: True)
    assert bangkokair_browser.relevant(["BKK"], ["USM"]) and bangkokair_browser.relevant(["MLE"], ["BKK"])
    assert not bangkokair_browser.relevant(["SIN"], ["HKG"])  # no Thai end
    assert not bangkokair_browser.relevant(["BKK"], ["NRT"])


def test_vietnamairlines_parse():
    js, cur = _des.parse(_load("vietnamairlines_sgn_han.json"))
    by = {"".join(s["carrier"] + s["number"] for s in j["segments"]): j for j in js}
    # matched booking.vietnamairlines.com: VN6002 USD 96.30, VN220 USD 100.60
    assert cur == "USD" and by["VN6002"]["total"] == 96.3 and by["VN220"]["total"] == 100.6
    assert any(len(j["segments"]) == 2 for j in js)  # via Da Nang
    its = combine(_q("SGN", "HAN", "2026-10-22"), "vietnamairlines", "Vietnam Airlines", js, None, cur, "https://x",
                  vietnamairlines_browser.NAMES)
    assert min(i.price for i in its) == 96.3


def test_vietnamairlines_and_pal_relevance(monkeypatch):
    monkeypatch.setattr(_browser, "available", lambda headful=False: True)
    assert vietnamairlines_browser.relevant(["SGN"], ["NRT"]) and not vietnamairlines_browser.relevant(["NRT"], ["ICN"])
    assert philippineairlines_browser.relevant(["MNL"], ["CEB"])
    assert philippineairlines_browser.relevant(["LAX"], ["MNL"]) and not philippineairlines_browser.relevant(["LAX"], ["NRT"])
    monkeypatch.setattr(_browser, "available", lambda headful=False: False)
    assert not vietnamairlines_browser.relevant(["SGN"], ["HAN"]) and not philippineairlines_browser.relevant(["MNL"], ["CEB"])


def test_philippineairlines_parse():
    js, cur = _des.parse(_load("philippineairlines_mnl_ceb.json"))
    by = {j["segments"][0]["number"]: j for j in js}
    # matched booking.philippineairlines.com: PR1841 PHP 2,795; day's cheapest PR1863 PHP 2,235
    assert cur == "PHP" and by["1841"]["total"] == 2795.0 and by["1863"]["total"] == 2235.0


@pytest.mark.live
def test_bangkokair_live():
    if not _browser.available():
        pytest.skip("needs Chrome and Playwright")
    its = _live(lambda: bangkokair_browser.search(_q("BKK", "USM", _future())))
    assert its and its[0].slices[0].segments[0].carrier == "PG"


@pytest.mark.live
def test_vietnamairlines_live():
    if not _browser.available():
        pytest.skip("needs Chrome and Playwright")
    its = _live(lambda: vietnamairlines_browser.search(_q("SGN", "HAN", _future())))
    assert its and its[0].currency == "USD"


@pytest.mark.live
def test_philippineairlines_live():
    if not _browser.available():
        pytest.skip("needs Chrome and Playwright")
    its = _live(lambda: philippineairlines_browser.search(_q("MNL", "CEB", _future())))
    assert its and its[0].currency == "PHP"


# --- Air Niugini (Sabre DX) ---------------------------------------------------------

def test_airniugini_parse():
    data = _load("airniugini_pom_bne.json")
    js, cur = airniugini_browser.parse(data)
    # matched dx-flights.airniugini.com.pg: PX3 and PX5 "From 950.20 PGK" (607 + 343.20 taxes)
    assert cur == "PGK" and [(j["segments"][0]["number"], j["total"]) for j in js[:2]] == [("3", 950.2), ("5", 950.2)]
    s = js[0]["segments"][0]
    assert s["departure"] == "2026-10-22T06:30:00+10:00" and s["duration"] == 190 and js[0]["fare"] == "YV"
    assert [x["number"] for x in js[2]["segments"]] == ["98", "3402"]  # via Cairns
    assert airniugini_browser.parse(data, adults=2)[0][0]["total"] == 1900.4  # amounts are per adult
    assert airniugini_browser.parse(data, "business")[0][0]["total"] == 4845.2
    assert airniugini_browser.parse({}) == ([], None)


def test_airniugini_relevance_and_deeplink(monkeypatch):
    monkeypatch.setattr(_browser, "available", lambda headful=False: True)
    assert airniugini_browser.relevant(["POM"], ["BNE"]) and airniugini_browser.relevant(["SYD"], ["LAE"])
    assert not airniugini_browser.relevant(["SYD"], ["BNE"])
    u = airniugini_browser.deeplink("POM", "BNE", date(2026, 10, 22), 2)
    assert u.endswith("#/flight-selection?journeyType=one-way&activeMonth=10-22-2026&date=10-22-2026"
                      "&origin=POM&destination=BNE&ADT=2&CHD=0&INF=0&promoCode=")


@pytest.mark.live
def test_airniugini_live():
    if not _browser.available():
        pytest.skip("needs Chrome and Playwright")
    its = _live(lambda: airniugini_browser.search(_q("POM", "BNE", _future())))
    if not its:
        pytest.skip("no Air Niugini flight that day")
    assert its[0].slices[0].segments[0].carrier == "PX"
