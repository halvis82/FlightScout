"""Wave 2 sources: ITA Matrix, Skiplagged (hidden city), more booking sites and
airlines. Offline: parsers against small saved responses. Live
(FLIGHTSCOUT_LIVE=1): one real search each, skipped on a bot wall."""

import base64
import json
from datetime import date, timedelta
from urllib.parse import unquote

import pytest

from conftest import FIXTURES
from flightscout.models import SearchQuery
from flightscout.sources import (_browser, agoda, avianca_browser, easemytrip, ita, ixigo_browser, kayakweb, sas_browser,
                                 skiplagged)
from flightscout.sources._airline import combine


def load(name):
    return json.loads((FIXTURES / name).read_text())


def q(o, d, dep, ret=None, **kw):
    return SearchQuery(origins=[o], destinations=[d], departure=date.fromisoformat(dep),
                       return_date=date.fromisoformat(ret) if ret else None, **kw)


def _live_date(days=45):
    return (date.today() + timedelta(days=days)).isoformat()


# ---- ITA Matrix ----------------------------------------------------------

def test_ita_parse_round_trip_with_details():
    fx = load("ita_osl_lax_rt.json")
    its = ita.parse(fx["data"], q("OSL", "LAX", "2026-11-12", "2026-11-19"), fx["details"], "https://m")
    assert [i.price for i in its] == [784.33, 1071.43, 1098.83]  # matched the Matrix page ($785, $1,072, $1,099)
    a = its[0]
    assert a.source == "ita" and a.currency == "USD" and a.seller == ita.SELLER and a.seller_kind == "metasearch"
    assert a.trip_type == "roundtrip"
    assert [s.carrier + s.flight_number for s in a.slices[0].segments] == ["SK1455", "SK931"]
    s = a.slices[0].segments[1]
    assert s.departure.isoformat() == "2026-11-12T14:20:00" and s.arrival.isoformat() == "2026-11-12T17:00:00"
    assert s.duration_min == 700 and s.aircraft == "Airbus A330"
    assert a.slices[0].duration_min == 960  # UTC based: 10:00+01 to 17:00-08
    assert a.slices[1].segments[-1].arrival.isoformat() == "2026-11-20T18:15:00"
    assert "does not sell tickets" in a.warnings[0]


def test_ita_parse_nonstops_without_details_and_skips_unexpanded():
    fx = load("ita_san_bos.json")
    its = ita.parse(fx["data"], q("SAN", "BOS", "2026-11-12"), fx["details"])
    assert [i.price for i in its] == [128.4, 154.4, 248.2]  # Google Flights: $129 for B6 620
    b6 = its[0].slices[0].segments[0]
    assert (b6.carrier, b6.flight_number, b6.origin, b6.destination) == ("B6", "620", "SAN", "BOS")
    assert b6.departure.isoformat() == "2026-11-12T11:41:00" and b6.duration_min == 348
    assert [s.carrier + s.flight_number for s in its[2].slices[0].segments] == ["AA1694", "AA2349"]
    # a connection without its bookingDetails has no segment times: skipped
    assert [i.price for i in ita.parse(fx["data"], q("SAN", "BOS", "2026-11-12"), {})] == [128.4, 154.4]
    assert [i.price for i in ita.parse(fx["data"], q("SAN", "BOS", "2026-11-12", max_stops=0), fx["details"])] \
        == [128.4, 154.4]


def test_ita_request_and_url():
    qq = q("OSL", "LAX", "2026-11-12", "2026-11-19", adults=2, cabin="business", currency="nok")
    inp = ita.inputs(qq, ["OSL"], ["LAX"])
    assert inp["pax"] == {"adults": 2} and inp["cabin"] == "BUSINESS" and inp["currency"] == "NOK"
    assert [(s["origins"], s["destinations"], s["date"]) for s in inp["slices"]] == [
        (["OSL"], ["LAX"], "2026-11-12"), (["LAX"], ["OSL"], "2026-11-19")]
    url = ita.search_url(qq, ["OSL"], ["LAX"], "SESS", "SET")
    assert url.startswith("https://matrix.itasoftware.com/flights?search=")
    s = json.loads(base64.b64decode(unquote(url.split("search=")[1])))
    assert s["type"] == "round-trip" and s["slices"][0]["dates"]["returnDate"] == "2026-11-19"
    assert s["solution"] == {"sessionId": "SESS", "yd": True, "wh": "SET", "Wi": None}
    assert ita.money("USD784.33") == (784.33, "USD") and ita.money("") is None
    assert ita.unwrap('--b\r\nContent-Type: application/json\r\n\r\n{"a": {"b": 1}}\r\n--b--') == {"a": {"b": 1}}


def test_ita_key_is_read_from_the_bundle(monkeypatch):
    class R:
        def __init__(self, text):
            self.text = text

    class C:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def get(self, url):
            if url.endswith("matrix.itasoftware.com/"):
                return R('<script src="//www.gstatic.com/alkali/abc.js"></script>')
            return R('D7.DEFAULT="AIzaDEFAULTxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",D7.matrix="AIza' + "k" * 35 + '",')

    monkeypatch.setattr(ita, "_client", lambda: C())
    assert ita.api_key() == "AIza" + "k" * 35


@pytest.mark.live
def test_ita_live():
    its = ita.search(q("SAN", "SEA", _live_date()))
    assert its and all(i.price > 20 and i.currency == "USD" for i in its)
    assert its[0].booking_url.startswith("https://matrix.itasoftware.com/flights?search=")


# ---- Skiplagged ----------------------------------------------------------

def test_skiplagged_one_way_hidden_city():
    its = skiplagged.parse(load("skiplagged_san_sea.json"), q("SAN", "SEA", "2026-11-12"), "SAN", "SEA")
    assert [i.price for i in its] == [79, 85, 89, 109, 109, 109]  # the results page: $79, $85, $89, $109
    h = its[0]
    assert h.source == "skiplagged" and h.seller == "Skiplagged" and h.currency == "USD"
    # ticketed SAN-SEA-PDX, flown SAN-SEA only
    assert [s.carrier + s.flight_number for s in h.slices[0].segments] == ["DL2508"]
    assert h.slices[0].destination == "SEA" and h.slices[0].duration_min == 191
    assert h.warnings and h.warnings[0].startswith("hidden city: don't check bags, final leg must be skipped")
    assert "ticket is to PDX via SEA" in h.warnings[0]
    f9 = its[1]
    assert [s.carrier + s.flight_number for s in f9.slices[0].segments] == ["F94990", "F91175"]
    assert not f9.warnings and not f9.self_transfer
    assert h.booking_url == "https://skiplagged.com/flights/SAN/SEA/2026-11-12"
    assert [i.price for i in skiplagged.parse(load("skiplagged_san_sea.json"), q("SAN", "SEA", "2026-11-12",
                                                                                  max_stops=0), "SAN", "SEA")] \
        == [79, 89, 109, 109, 109]


def test_skiplagged_round_trip():
    fx = load("skiplagged_san_sea_rt.json")
    its = skiplagged.parse(fx["search"], q("SAN", "SEA", "2026-11-12", "2026-11-19"), "SAN", "SEA", fx["lazy"])
    reg = sorted((i for i in its if not i.self_transfer), key=lambda i: i.price)
    # AS608 then a return: $157 x4 and $182, exactly the page after picking AS608
    assert [i.price for i in reg] == [157, 157, 157, 157, 182]
    assert [s.carrier + s.flight_number for sl in reg[0].slices for s in sl.segments] == ["AS608", "AS1365"]
    assert reg[0].trip_type == "roundtrip" and not reg[0].warnings
    hid = [i for i in its if i.self_transfer]
    # hidden city outbound: $79 + a $109 return one way, two tickets (the page: $188)
    assert hid and {i.price for i in hid} == {188}
    assert any(w.startswith("hidden city:") for w in hid[0].warnings) and skiplagged.TWO_OW in hid[0].warnings
    assert reg[0].booking_url == "https://skiplagged.com/flights/SAN/SEA/2026-11-12/2026-11-19"


def test_skiplagged_business_skipped():
    assert skiplagged.search(q("SAN", "SEA", "2026-11-12", cabin="business")) == []


@pytest.mark.live
def test_skiplagged_live():
    its = skiplagged.search(q("SAN", "SEA", _live_date()))
    assert its and all(i.currency == "USD" and i.price > 10 for i in its)
    assert all(i.slices[0].origin == "SAN" and i.slices[0].destination == "SEA" for i in its)


# ---- EaseMyTrip -----------------------------------------------------------

def test_easemytrip_parse():
    r = easemytrip.parse(load("easemytrip_bom_del.json"), "BOM", "DEL")
    # the listing page: SG 613 21:50 \u20b96,832, IX 2207 (1 stop) \u20b98,054; NMI (Navi Mumbai) dropped
    assert [(p, [s.carrier + s.flight_number for s in sl.segments]) for p, sl, _ in r] == [
        (6832.0, ["SG613"]), (7158.0, ["6E2049", "6E6867"]), (8054.0, ["IX2207", "IX2244"])]
    sg = r[0][1]
    assert sg.segments[0].departure.isoformat() == "2026-11-12T21:50:00" and sg.duration_min == 125
    assert sg.segments[0].carrier_name == "SpiceJet" and sg.segments[0].duration_min == 125
    assert r[2][1].duration_min == 610 and r[2][1].segments[1].origin == "BHO"
    assert [p for p, _, _ in easemytrip.parse(load("easemytrip_bom_del.json"), "BOM", "DEL", max_stops=0)] == [6832.0]


def test_easemytrip_search_round_trip_is_two_tickets(monkeypatch):
    calls = []
    monkeypatch.setattr(easemytrip, "_fetch", lambda o, d, day, a, c: calls.append((o, d, str(day))) or load(
        "easemytrip_bom_del.json") if o == "BOM" else {"C": {}, "dctFltDtl": {"1": {
            "OG": "DEL", "DT": "BOM", "DDT": "Thu-19Nov2026", "ADT": "Thu-19Nov2026", "DTM": "19:00", "ATM": "21:10",
            "FN": "612", "AC": "SG", "DUR": "02h 10m"}}, "j": [{"s": [{"TF": 6244, "b": [{"FL": [1]}]}]}]})
    its = easemytrip.search(q("BOM", "DEL", "2026-11-12", "2026-11-19"))
    assert its[0].price == 6832 + 6244 and its[0].currency == "INR" and its[0].self_transfer
    assert easemytrip.TWO_OW in its[0].warnings and its[0].seller_kind == "ota"
    assert its[0].booking_url.startswith("https://www.easemytrip.com/flight-search/listing?srch=BOM-BOM|DEL-DEL|12%2F11%2F2026-19%2F11%2F2026")
    assert "isdm=true" in its[0].booking_url


@pytest.mark.live
def test_easemytrip_live():
    its = easemytrip.search(q("BOM", "DEL", _live_date()))
    assert its and all(i.currency == "INR" and i.price > 500 for i in its)


# ---- Agoda (KAYAK white label) ---------------------------------------------

def test_agoda_reuses_kayak_under_its_brand():
    its = kayakweb.parse(load("kayak_lax_jfk.json"), q("LAX", "JFK", "2026-11-06"), "agoda", "flights.agoda.com",
                         "LAX", "JFK")
    assert its and all(i.source == "agoda" for i in its)
    assert its[0].booking_url.startswith("https://flights.agoda.com/flights/LAX-JFK/2026-11-06/f")
    assert "on Agoda" in its[0].warnings[0]
    assert kayakweb.domain("agoda", "NOK") == ("flights.agoda.com", "USD")


@pytest.mark.live
def test_agoda_live():
    its = agoda.search(q("LAX", "JFK", _live_date()))
    assert its and all(i.source == "agoda" and i.currency == "USD" for i in its)


# ---- ixigo -----------------------------------------------------------------

def test_ixigo_parse_nonstops():
    its = ixigo_browser.parse((FIXTURES / "ixigo_bom_del.sse").read_text(), q("BOM", "DEL", "2026-11-12"), "BOM", "DEL")
    # the results list: SG 613 \u20b96,452 (struck \u20b96,832); connections and NMI are skipped
    assert [(i.price, i.slices[0].segments[0].carrier + i.slices[0].segments[0].flight_number) for i in its] == [
        (6452.0, "SG613"), (7398.0, "QP1117")]
    a = its[0]
    assert a.source == "ixigo" and a.currency == "INR" and a.seller == "ixigo" and a.seller_kind == "ota"
    s = a.slices[0].segments[0]
    assert s.departure.isoformat() == "2026-11-12T21:50:00" and s.arrival.isoformat() == "2026-11-12T23:55:00"
    assert "6832 INR before it" in a.warnings[1]
    assert a.booking_url == ("https://www.ixigo.com/search/result/flight?from=BOM&to=DEL&date=12112026&adults=1"
                             "&children=0&infants=0&class=e&source=Search+Form")


def test_ixigo_skips_round_trips_and_without_browser(monkeypatch):
    assert ixigo_browser.search(q("BOM", "DEL", "2026-11-12", "2026-11-19")) == []
    monkeypatch.setattr(_browser, "available", lambda headful=False: False)
    assert ixigo_browser.search(q("BOM", "DEL", "2026-11-12")) == []


@pytest.mark.live
def test_ixigo_live():
    if not _browser.available():
        pytest.skip("needs Chrome and Playwright")
    its = ixigo_browser.search(q("BOM", "DEL", _live_date()))
    assert its and all(i.currency == "INR" and i.slices[0].stops == 0 for i in its)


# ---- Avianca ---------------------------------------------------------------

def test_avianca_parse():
    js, cur = avianca_browser.parse(load("avianca_bog_mde.json"))
    assert cur == "USD" and len(js) == 3
    a = js[0]
    assert a["total"] == 116.8 and a["fare"] == "BASIC" and a["seats"] == 9  # the page: "From USD 116,80"
    its = combine(q("BOG", "MDE", "2026-11-12"), "avianca", "Avianca", js, None, cur, "https://x", avianca_browser.NAMES)
    s = its[0].slices[0].segments[0]
    assert (s.carrier, s.flight_number, s.departure.isoformat()) == ("AV", "9350", "2026-11-12T04:35:00")
    assert s.duration_min == 60 and its[0].slices[0].duration_min == 60 and s.carrier_name == "Avianca"


def test_avianca_relevance_and_link(monkeypatch):
    monkeypatch.setattr(_browser, "available", lambda headful=False: True)
    assert avianca_browser.relevant(["BOG"], ["MDE"]) and avianca_browser.relevant(["MIA"], ["BOG"])
    assert not avianca_browser.relevant(["OSL"], ["BCN"])
    u = avianca_browser.deeplink("BOG", "MDE", date(2026, 11, 12), date(2026, 11, 19), 2)
    assert "tripType=round-trip" in u and "nbAdults=2" in u and u.endswith("&returnDate=2026-11-19")


@pytest.mark.live
def test_avianca_live():
    if not _browser.available():
        pytest.skip("needs Chrome and Playwright")
    its = avianca_browser.search(q("BOG", "MDE", _live_date()))
    assert its and all(i.slices[0].origin == "BOG" and i.price > 10 for i in its)


# ---- SAS -------------------------------------------------------------------

def test_sas_parse():
    js, cur = sas_browser.parse(load("sas_osl_cph.json"))
    # flysas.com flight selection: 05:55 Economy \u20ac79,32, 08:00 \u20ac88,02, 09:00 \u20ac125,50 "3 left"
    assert cur == "EUR" and [(x["total"], x["segments"][0]["number"], x["seats"]) for x in js] == [
        (79.32, "1461", 9), (88.02, "451", 9), (125.5, "455", 3)]
    assert [x["total"] for x in sas_browser.parse(load("sas_osl_cph.json"), "business")[0]] == [203.5, 203.5, 254.5]
    its = combine(q("OSL", "CPH", "2026-11-12"), "sas", "SAS", js, None, cur, "https://x", sas_browser.NAMES)
    s = its[0].slices[0].segments[0]
    assert (s.carrier, s.flight_number, s.departure.isoformat(), s.duration_min) == ("SK", "1461", "2026-11-12T05:55:00", 80)
    assert any("few seats" in w for w in its[2].warnings)


def test_sas_link_and_relevance(monkeypatch):
    monkeypatch.setattr(_browser, "available", lambda headful=False: True)
    assert sas_browser.deeplink("OSL", "CPH", date(2026, 11, 12), date(2026, 11, 19), 2).startswith(
        "https://www.flysas.com/en/book/flights/?search=RT_OSL-CPH-20261112-20261119_a2c0i0y0")
    assert sas_browser.relevant(["OSL"], ["LHR"]) and not sas_browser.relevant(["MAD"], ["LHR"])


@pytest.mark.live
def test_sas_live():
    if not _browser.available():
        pytest.skip("needs Chrome and Playwright")
    try:
        its = sas_browser.search(q("OSL", "CPH", _live_date()))
    except RuntimeError as e:  # Cloudflare lets the page through only now and then
        pytest.skip(f"blocked: {e}")
    assert its and all(i.slices[0].origin == "OSL" for i in its)
