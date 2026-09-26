"""Direct airline sources for Europe, the Middle East, Africa, Asia and Oceania.
Offline: parsers against saved responses. Live (FLIGHTSCOUT_LIVE=1): one real
search per airline, skipped when Chrome or Playwright is missing."""

import json
from datetime import date, timedelta

import pytest

from conftest import FIXTURES
from flightscout.models import SearchQuery
from flightscout.sources import (_browser, _c_ezycommerce, aegean_browser, aerlingus, afklm_browser, akasa_browser, etihad_browser, finnair_browser, flydubai_browser, flysafair, jazeera, jejuair_browser, jet2, level_browser, qatar_browser, skyexpress, spicejet_browser, tap_browser, tigerair_browser, vietjet_browser, virginaustralia_browser, vueling, zipair_browser)
from flightscout.sources._airline import combine


# ---- group A ------------------------------------------------------------
# ---- group A: Nordic / Baltic / Central Europe (Finnair, ...) ----




def _load_a(name):
    return json.loads((FIXTURES / name).read_text())


def _q_a(o, d, dep, ret=None, **kw):
    return SearchQuery(origins=[o], destinations=[d], departure=date.fromisoformat(dep),
                       return_date=date.fromisoformat(ret) if ret else None, **kw)


def test_finnair_parse():
    js, cur = finnair_browser.parse(_load_a("finnair_arn_bkk.json"))
    assert cur == "SEK" and len(js) == 3
    j = next(x for x in js if x["segments"][0]["number"] == "802")
    assert j["total"] == 10776.0 and j["fare"] == "Economy Light"  # 2 adults, matched finnair.com
    assert [s["carrier"] + s["number"] for s in j["segments"]] == ["AY802", "AY145"]
    assert j["duration"] == 1600
    its = combine(_q_a("ARN", "BKK", "2026-11-12", adults=2), "finnair", "Finnair", js, None, cur, "https://x",
                  finnair_browser.NAMES)
    assert its[0].price == 10776.0 and its[0].slices[0].stops == 1
    assert its[0].slices[0].segments[1].departure.isoformat() == "2026-11-13T00:15:00"
    biz, _ = finnair_browser.parse(_load_a("finnair_arn_bkk.json"), cabin="business")
    assert all(b["total"] > 10776 for b in biz)


def test_finnair_deeplink_and_relevance(monkeypatch):
    monkeypatch.setattr(_browser, "available", lambda headful=False: True)
    url = finnair_browser.deeplink("HEL", "ARN", date(2026, 10, 21), date(2026, 10, 25), 2)
    assert url.startswith("https://www.finnair.com/en/booking/flight-selection?json=")
    assert "%22origin%22:%22ARN%22" in url and "%22adults%22:2" in url
    assert finnair_browser.relevant(["HEL"], ["LHR"])
    assert finnair_browser.relevant(["ARN"], ["BKK"])  # via Helsinki
    assert not finnair_browser.relevant(["MAD"], ["LHR"])
    assert not finnair_browser.relevant(["JFK"], ["LAX"])


@pytest.mark.live
def test_finnair_live():
    if not _browser.available():
        pytest.skip("needs Chrome and Playwright")
    day = date.today() + timedelta(days=40)
    its = finnair_browser.search(SearchQuery(origins=["HEL"], destinations=["ARN"], departure=day))
    assert its and its[0].source == "finnair" and its[0].currency == "EUR"
    assert all(s.carrier == "AY" for i in its for sl in i.slices for s in sl.segments)


def test_finnair_round_trip_mixed_currency(monkeypatch):
    from flightscout import fx
    from flightscout.sources import finnair_browser as m

    monkeypatch.setattr(_browser, "available", lambda headful=False: True)
    monkeypatch.setattr(fx, "convert", lambda amount, frm, to: amount / 10 if (frm, to) == ("SEK", "EUR") else amount)
    js, _ = m.parse(_load_a("finnair_arn_bkk.json"))
    one = [dict(js[0], segments=[dict(s, origin="HEL", destination="ARN") for s in js[0]["segments"][:1]])]
    back = [dict(js[0], segments=[dict(s, origin="ARN", destination="HEL") for s in js[0]["segments"][:1]])]

    def fake_bound(o, d, day, adults, cabin):
        return ([{**one[0], "total": 51.48}], "EUR") if o == "HEL" else ([{**back[0], "total": 1000.0}], "SEK")

    monkeypatch.setattr(m, "_bound", fake_bound)
    its = m.search(_q_a("HEL", "ARN", "2026-10-21", "2026-10-25"))
    assert its and its[0].currency == "EUR" and its[0].price == 151.48  # SEK return converted
    assert m.parse({}) == ([], None)  # NO_FLIGHTS_FOUND day


# ---- group B ------------------------------------------------------------
def _load_b(name):
    return json.loads((FIXTURES / name).read_text())


def _q_b(o, d, dep, ret=None, **kw):
    return SearchQuery(origins=[o], destinations=[d], departure=date.fromisoformat(dep),
                       return_date=date.fromisoformat(ret) if ret else None, **kw)


# --- Jet2 -------------------------------------------------------------------

def test_jet2_parse_round_trip():
    outs, backs, cur = jet2.parse(_load_b("jet2_man_tfs.json"), date(2026, 12, 19), date(2026, 12, 26))
    assert cur == "GBP"
    assert [(j["number"], j["total"]) for j in outs] == [("LS829", 552.0), (None, 604.0)]
    assert outs[0]["departure"] == "2026-12-19T14:25:00+00:00" and outs[0]["duration"] == 285
    assert len(backs) == 4 and backs[0]["number"] == "LS1800" and backs[0]["total"] == 120.0
    assert backs[0]["arrival"].startswith("2026-12-27T00:35")  # past midnight
    s = jet2._slice(outs[0])
    assert s.segments[0].flight_number == "829" and s.segments[0].carrier == "LS" and s.duration_min == 285
    assert jet2._slice(outs[1]).segments[0].flight_number is None
    # a date the page did not select is ignored
    assert jet2.parse(_load_b("jet2_man_tfs.json"), date(2026, 12, 20))[0] == []


def test_jet2_relevance_and_deeplink():
    assert jet2.relevant(["MAN"], ["ALC"])
    assert jet2.relevant(["LGW", "OSL"], ["PMI"])
    assert not jet2.relevant(["ALC"], ["MAN"])  # one ways from abroad are not served
    assert not jet2.relevant(["MAN"], ["JFK"])
    url = jet2.deeplink("MAN", "ALC", date(2026, 11, 10), date(2026, 11, 17), 2, "alicante")
    assert url.startswith("https://www.jet2.com/en/search-results/alicante?dep=MAN&arr=ALC&from=2026-11-10")
    assert "selectedDate=10-11-2026&adults=2" in url and "duration=7&oneway=false" in url


def test_jet2_page_data():
    html = "<script>var searchInitialResponseJson = '{\\\"isError\\\":true,\\\"trips\\\":{}}';\n</script>"
    assert jet2.page_data(html) == {"isError": True, "trips": {}}


# --- Aer Lingus ---------------------------------------------------------------

def test_aerlingus_parse_round_trip():
    outs, backs, cur = aerlingus.parse(_load_b("aerlingus_dub_jfk.json"), adults=2)
    assert cur == "EUR"
    direct = outs[0]
    assert direct["segments"][0]["number"] == "105" and direct["total"] == 441.5  # 220.75 x 2
    assert direct["duration"] == 464 and direct["fare"] == "saver"
    via = next(j for j in outs if len(j["segments"]) == 2)
    assert via["segments"][0]["origin"] == "DUB" and via["segments"][-1]["destination"] == "JFK"
    its = combine(_q_b("DUB", "JFK", "2026-11-10", "2026-11-17", adults=2), "aerlingus", "Aer Lingus", outs, backs,
                  cur, "https://x", aerlingus.NAMES)
    best = min(its, key=lambda i: i.price)
    assert best.price == 441.5 + 354.72 and best.trip_type == "roundtrip"
    assert best.slices[0].segments[0].carrier == "EI"


def test_aerlingus_relevance_and_deeplink():
    assert aerlingus.relevant(["DUB"], ["LHR"])
    assert aerlingus.relevant(["BOS"], ["BCN"])  # sold via Dublin
    assert not aerlingus.relevant(["JFK"], ["LAX"])
    assert not aerlingus.relevant(["CDG"], ["NRT"])
    url = aerlingus.deeplink("DUB", "LHR", date(2026, 11, 10), date(2026, 11, 17), 2)
    assert "fareType=RETURN" in url and "numAdults=2" in url
    assert "sourceAirportCode_1=LHR&destinationAirportCode_1=DUB&departureDate_1=2026-11-17" in url


# --- Air France / KLM ------------------------------------------------------------

def test_afklm_parse():
    js, cur = afklm_browser.parse(_load_b("afklm_ams_lhr.json"))
    assert cur == "USD"
    assert [(j["segments"][0]["carrier"] + j["segments"][0]["number"], j["total"]) for j in js] == [
        ("KL1001", 115.5), ("KL1003", 119.5), ("AF5473", 174.1)]
    via = js[2]
    assert [s["origin"] for s in via["segments"]] == ["AMS", "CDG"] and via["segments"][0]["operated_by"] == "KL"
    assert via["duration"] == 245 and via["fare"] == "BASIC"
    sl = afklm_browser._slice(js[0])
    assert sl.segments[0].flight_number == "1001" and sl.duration_min == 80
    assert afklm_browser.parse(_load_b("afklm_ams_lhr.json"), "business")[0][0]["total"] == 447.2


def test_afklm_deeplink_and_relevance(monkeypatch):
    monkeypatch.setattr(_browser, "available", lambda headful=False: True)
    url = afklm_browser.deeplink("AMS", "LHR", date(2026, 11, 10), date(2026, 11, 17), 2)
    assert "pax=2:0:0:0:0:0:0:0&cabinClass=ECONOMY" in url
    assert "connections=AMS:A:20261110%3ELHR:A-LHR:A:20261117%3EAMS:A" in url
    assert afklm_browser.relevant(["AMS"], ["LHR"])
    assert afklm_browser.relevant(["LHR"], ["NRT"])  # long haul from Europe, sold over AMS/CDG
    assert not afklm_browser.relevant(["LHR"], ["BCN"])  # intra Europe without FR/NL
    assert not afklm_browser.relevant(["JFK"], ["LAX"])


# --- live ----------------------------------------------------------------------

def _soon_b(days=45):
    return (date.today() + timedelta(days=days)).isoformat()


@pytest.mark.live
def test_jet2_live():
    its = jet2.search(_q_b("MAN", "ALC", _soon_b(), _soon_b(52)))
    assert its and all(i.source == "jet2" and i.currency == "GBP" and i.price > 0 for i in its)
    assert its[0].booking_url.startswith("https://www.jet2.com/en/search-results/")


@pytest.mark.live
def test_aerlingus_live():
    its = aerlingus.search(_q_b("DUB", "LHR", _soon_b()))
    assert its and all(i.source == "aerlingus" and i.price > 0 for i in its)
    assert {s.carrier for i in its for sl in i.slices for s in sl.segments} >= {"EI"}


@pytest.mark.live
def test_afklm_live():
    if not _browser.available():
        pytest.skip("needs Chrome and Playwright")
    its = afklm_browser.search(_q_b("AMS", "CDG", _soon_b()))
    assert its and all(i.source == "afklm" and i.price > 0 for i in its)
    assert {s.carrier for i in its for sl in i.slices for s in sl.segments} & {"KL", "AF"}


# ---- group C ------------------------------------------------------------
# --- fork C: Vueling, Level, Iberia, TAP, Aegean, Sky Express ---




def _load_c(name):
    return json.loads((FIXTURES / name).read_text())


def _q_c(o, d, dep="2026-11-12", ret=None, **kw):
    return SearchQuery(origins=[o], destinations=[d], departure=date.fromisoformat(dep),
                       return_date=date.fromisoformat(ret) if ret else None, **kw)


def test_vueling_parse_connections():
    js, cur = vueling.parse(_load_c("vueling_lcg_fco.json"))
    assert cur == "EUR" and len(js) == 2
    a = js[0]
    assert a["total"] == 55.48 and a["fare"] == "BA"
    assert [s["carrier"] + s["number"] for s in a["segments"]] == ["VY1135", "VY6010"]
    assert a["segments"][0]["departure"] == "2026-11-12T08:50:00"  # local, bogus Z stripped
    assert a["duration"] == 325  # from the legs' UTC times
    js2, _ = vueling.parse(_load_c("vueling_lcg_fco.json"), adults=2)
    assert js2[0]["total"] == 110.96
    its = combine(_q_c("LCG", "FCO"), "vueling", "Vueling", js, None, cur, "https://x", vueling.NAMES)
    assert its[0].slices[0].stops == 1 and its[0].seller_kind == "airline"


def test_vueling_relevance_and_deeplink():
    assert vueling.relevant(["BCN"], ["ORY"])
    assert not vueling.relevant(["BCN"], ["JFK"])
    u = vueling.deeplink("BCN", "ORY", date(2026, 11, 12), date(2026, 11, 16), 2)
    assert "o=BCN&d=ORY&dd=2026-11-12&adt=2" in u and u.endswith("&rd=2026-11-16")


def _future_c(days=50):
    return (date.today() + timedelta(days=days)).isoformat()


@pytest.mark.live
def test_vueling_live():
    its = vueling.search(_q_c("BCN", "ORY", _future_c()))
    assert its and all(i.currency == "EUR" and i.price > 10 for i in its)
    assert its[0].slices[0].segments[0].carrier == "VY"




def test_level_parse_connections_and_cabins():
    outs, backs, cur = level_browser.parse(_load_c("level_fco_eze.json"))
    assert cur == "EUR" and backs is None and len(outs) == 2
    a = outs[0]
    assert a["total"] == 1180.87 and a["fare"] == "LIGHT" and a["duration"] == 2240
    # the Vueling feeder is reported as the operating flight, not LEVEL's marketing number
    assert [s["carrier"] + s["number"] for s in a["segments"]] == ["VY6001", "LL2603"]
    prem, _, _ = level_browser.parse(_load_c("level_fco_eze.json"), "premium")
    assert prem[0]["total"] == 1580.87
    its = combine(_q_c("FCO", "EZE", "2026-11-10"), "level", "LEVEL", outs, None, cur, "https://x", level_browser.NAMES)
    assert its[0].price == 1180.87 and its[0].slices[0].stops == 1


def test_level_relevance_and_deeplink(monkeypatch):
    monkeypatch.setattr(_browser, "available", lambda headful=False: True)
    assert level_browser.relevant(["BCN"], ["JFK"])
    assert level_browser.relevant(["FCO"], ["EZE"])  # Vueling feeder via BCN
    assert not level_browser.relevant(["BCN"], ["MAD"])
    assert not level_browser.relevant(["JFK"], ["LAX"])
    u = level_browser.deeplink("BCN", "JFK", date(2026, 11, 5), date(2026, 11, 12), 2)
    assert "o1=BCN&d1=JFK&dd1=2026-11-05&dd2=2026-11-12&ADT=2" in u and "r=true" in u


@pytest.mark.live
def test_level_live():
    if not _browser.available():
        pytest.skip("needs Chrome and Playwright")
    start = date.today() + timedelta(days=30)
    cal = level_browser.dates("BCN", "JFK", start, start + timedelta(days=30))  # LEVEL does not fly daily
    assert cal and all(c.source == "level" and c.price > 50 for c in cal)
    its = level_browser.search(_q_c("BCN", "JFK", cal[0].departure.isoformat()))
    assert its and its[0].currency == "EUR" and its[0].slices[0].segments[0].carrier == "LL"
    assert abs(its[0].price - cal[0].price) <= 1  # the calendar shows the fare rounded up to the euro




def test_skyexpress_parse_round_trip():
    data = _load_c("skyexpress_jmk_jtr.json")
    outs = _c_ezycommerce.parse(data, 0)
    backs = _c_ezycommerce.parse(data, 1)
    assert [j["total"] for j in outs] == [158.08, 125.08]
    assert [s["carrier"] + s["number"] for s in outs[0]["segments"]] == ["GQ231", "GQ342"]
    assert outs[0]["fare"] == "SKYJOY" and outs[0]["duration"] == 125
    assert backs[0]["fare"] == "SKYJOYPLUS"  # SKYjoy sold out on that flight
    assert _c_ezycommerce.parse(data, 0, "business") == [] and _c_ezycommerce.parse(data, 2) == []
    its = combine(_q_c("JMK", "JTR", "2026-10-22", "2026-10-26"), "skyexpress", "SKY express", outs, backs, "EUR",
                  "https://x", skyexpress.NAMES)
    assert min(i.price for i in its) == round(125.08 + 176.59, 2) and its[0].trip_type == "roundtrip"


def test_skyexpress_relevance_and_deeplink(monkeypatch):
    monkeypatch.setattr(skyexpress.EZY, "network", lambda: {"ATH": ["HER", "JMK"], "HER": ["ATH"]})
    assert skyexpress.relevant(["ATH"], ["HER"])
    assert not skyexpress.relevant(["ATH"], ["OSL"])
    monkeypatch.setattr(skyexpress.EZY, "network", lambda: None)  # list down: Greece/Cyprus gate
    assert skyexpress.relevant(["ATH"], ["CDG"]) and not skyexpress.relevant(["OSL"], ["CDG"])
    u = skyexpress.deeplink("ATH", "HER", date(2026, 10, 22), date(2026, 10, 26), 2)
    assert "routes[1][from]=HER&routes[1][to]=ATH&routes[1][date]=2026-10-26" in u
    assert "passengers[0][count]=2" in u and u.endswith("execute=true")


@pytest.mark.live
def test_skyexpress_live():
    its = skyexpress.search(_q_c("ATH", "HER", _future_c(30)))
    assert its and its[0].currency == "EUR" and its[0].slices[0].segments[0].carrier == "GQ"




def test_tap_parse_round_trip_pairs():
    offers, cur = tap_browser.parse(_load_c("tap_mad_gru.json"))
    assert cur == "EUR" and len(offers) == 3
    x = offers[0]
    assert x["total"] == 729.42 and x["fare"] == "DISCINT"  # 381.56 out + 347.86 back, TAP's pair price
    assert [s["carrier"] + s["number"] for s in x["out"]["segments"]] == ["TP1011", "TP89"]
    assert [s["carrier"] + s["number"] for s in x["back"]["segments"]] == ["TP82", "TP1010"]
    assert x["out"]["segments"][0]["departure"] == "2026-11-12T10:20:00"  # local, bogus Z stripped
    assert tap_browser.parse(_load_c("tap_mad_gru.json"), "premium")[0] == []  # mixed cabin pairs skipped


def test_tap_relevance_and_deeplink(monkeypatch):
    monkeypatch.setattr(_browser, "available", lambda headful=False: True)
    assert tap_browser.relevant(["LIS"], ["OPO"])
    assert tap_browser.relevant(["MAD"], ["GRU"])  # Europe to Brazil via Lisbon
    assert not tap_browser.relevant(["MAD"], ["BCN"])
    assert not tap_browser.relevant(["JFK"], ["GRU"])
    u = tap_browser.deeplink("LIS", "OPO", date(2026, 10, 22), date(2026, 10, 29), 2)
    assert "origin=LIS&destination=OPO&depDate=22.10.2026&flightType=return&retDate=29.10.2026&adt=2" in u


def test_aegean_parse_fare_families():
    (js,) = aegean_browser.parse(_load_c("aegean_ath_her.json"))
    assert [(j["segments"][0]["number"], j["total"]) for j in js] == [("300", 49.62), ("304", 58.62), ("306", 58.62)]
    a = js[0]
    assert a["fare"] == "NOBAG" and a["segments"][0]["departure"] == "2026-10-22T06:35:00" and a["duration"] == 55
    (biz,) = aegean_browser.parse(_load_c("aegean_ath_her.json"), "business")
    assert biz[0]["total"] == 165.62 and biz[0]["fare"] == "BUSINESSBA"
    its = combine(_q_c("ATH", "HER", "2026-10-22"), "aegean", "Aegean Airlines", js, None, "EUR", "https://x",
                  aegean_browser.NAMES)
    assert its[0].price == 49.62 and its[0].slices[0].segments[0].carrier_name == "Aegean Airlines"


def test_aegean_relevance_and_deeplink(monkeypatch):
    monkeypatch.setattr(_browser, "available", lambda headful=False: True)
    assert aegean_browser.relevant(["ATH"], ["HER"]) and aegean_browser.relevant(["LHR"], ["LCA"])
    assert not aegean_browser.relevant(["LHR"], ["CDG"])
    u = aegean_browser.deeplink("ATH", "HER", date(2026, 10, 22), date(2026, 10, 26), 2)
    assert "TravelType=R&AirportFrom=ATH&AirportTo=HER&DateDeparture=22%2F10%2F2026&DateReturn=26%2F10%2F2026" in u
    assert "AdultsNum=2" in u


@pytest.mark.live
def test_tap_live():
    if not _browser.available():
        pytest.skip("needs Chrome and Playwright")
    its = tap_browser.search(_q_c("LIS", "OPO", _future_c(30)))
    assert its and its[0].currency == "EUR" and its[0].slices[0].segments[0].carrier in ("TP", "NI")


@pytest.mark.live
def test_aegean_live():
    if not _browser.available():
        pytest.skip("needs Chrome and Playwright")
    try:
        its = aegean_browser.search(_q_c("ATH", "HER", _future_c(30)))
    except RuntimeError as e:
        if "Imperva" in str(e):
            pytest.skip(str(e))  # rate limited by the bot check, not a parsing failure
        raise
    assert its and its[0].currency == "EUR" and its[0].slices[0].segments[0].carrier in ("A3", "OA")


# ---- group D ------------------------------------------------------------
def _load_d(name):
    return json.loads((FIXTURES / name).read_text())


def test_flydubai_parse():
    js, cur = flydubai_browser.parse(_load_d("flydubai_dxb_tbs.json"))
    assert cur == "AED"
    by_num = {j["segments"][0]["number"]: j for j in js}
    assert by_num["721"]["total"] == 891 and by_num["721"]["fare"] == "LITE"  # UI: FZ 721 from AED 891
    assert by_num["711"]["total"] == 1046  # UI: FZ 711 from AED 1,046
    assert by_num["721"]["duration"] == 215 and by_num["721"]["segments"][0]["aircraft"]
    two, _ = flydubai_browser.parse(_load_d("flydubai_dxb_tbs.json"), adults=2)
    assert min(j["total"] for j in two) == 1782
    biz, _ = flydubai_browser.parse(_load_d("flydubai_dxb_tbs.json"), cabin="business")
    assert biz and all(j["total"] > 1046 for j in biz)
    q = SearchQuery(origins=["DXB"], destinations=["TBS"], departure=date(2026, 11, 18))
    its = combine(q, "flydubai", "flydubai", js, None, cur, flydubai_browser.deeplink("DXB", "TBS", q.departure))
    assert its[0].price == 891 and its[0].slices[0].segments[0].carrier == "FZ"
    assert its[0].slices[0].duration_min == 215


def test_flydubai_strip_and_deeplink(monkeypatch):
    strip = flydubai_browser.parse_strip(_load_d("flydubai_dxb_tbs_strip.json"))
    assert [(str(d), p) for _, _, d, p, _ in strip][2:5] == [
        ("2026-11-17", 840), ("2026-11-18", 891), ("2026-11-19", 840)]
    url = flydubai_browser.deeplink("DXB", "KTM", date(2026, 10, 20), date(2026, 10, 27), 2)
    assert url.startswith("https://flights2.flydubai.com/en/results/rt/a2c0i0/DXB_KTM/20261020_20261027?")
    monkeypatch.setattr(_browser, "available", lambda headful=False: True)
    monkeypatch.setattr(flydubai_browser, "network", lambda: {"DXB", "KTM", "BEG", "LAX", "OSL"})
    assert flydubai_browser.relevant(["DXB"], ["KTM"])
    assert flydubai_browser.relevant(["BEG"], ["KTM"])
    assert not flydubai_browser.relevant(["OSL"], ["LAX"])  # Emirates codeshare points only


@pytest.mark.live
def test_flydubai_live():
    if not _browser.available():
        pytest.skip("needs Playwright and Chrome")
    day = date.today() + timedelta(days=45)
    q = SearchQuery(origins=["DXB"], destinations=["TBS"], departure=day)
    try:
        its = flydubai_browser.search(q)
    except RuntimeError as e:  # Akamai rate limits the flight list now and then
        if "403" in str(e):
            pytest.skip(str(e))
        raise
    assert its and its[0].currency == "AED" and its[0].seller == "flydubai"
    assert all(s.carrier in ("FZ", "EK") for it in its for sl in it.slices for s in sl.segments)
    cal = flydubai_browser.dates("DXB", "TBS", day, day + timedelta(days=6), "AED")
    assert cal and all(c.price > 0 for c in cal)


# ---- group E ------------------------------------------------------------
# --- Group E: Jazeera, FlySafair, Qatar, Etihad (fork E) ---




def _load_e(name):
    return json.loads((FIXTURES / name).read_text())


def _q_e(o, d, dep, ret=None, **kw):
    return SearchQuery(origins=[o], destinations=[d], departure=date.fromisoformat(dep),
                       return_date=date.fromisoformat(ret) if ret else None, **kw)


def test_jazeera_parse_round_trip():
    bounds = jazeera.parse(_load_e("jazeera_dxb_bey_rt.json"))
    assert [(o, d, c) for o, d, c, _ in bounds] == [("DXB", "BEY", "AED"), ("BEY", "DXB", "AED")]
    out, back = bounds[0][3], bounds[1][3]
    assert len(out) == 1 and out[0]["total"] == 1363.80  # 2 adults, the Light fare (AED 681.90 each on the site)
    assert [s["carrier"] + s["number"] for s in out[0]["segments"]] == ["J9122", "J9261"]
    assert out[0]["segments"][0]["departure"] == "2026-11-10T10:55:00" and out[0]["duration"] == 635
    its = combine(_q_e("DXB", "BEY", "2026-11-10", "2026-11-17", adults=2), "jazeera", "Jazeera Airways",
                  out, back, "AED", "https://x", jazeera.NAMES)
    assert its[0].price == 1363.80 + 1276.20 and its[0].trip_type == "roundtrip"
    assert its[0].slices[0].stops == 1


def test_jazeera_flight_id_fallback_and_deeplink():
    seg = jazeera._flight_from_id("Sjl_IDEyMX4gfn5LV0l_MTEvMTAvMjAyNiAwNjo1NX5EWEJ_MTEvMTAvMjAyNiAxMDoxMH5_")
    assert seg == {"origin": "KWI", "destination": "DXB", "departure": "2026-11-10T06:55:00",
                   "arrival": "2026-11-10T10:10:00", "carrier": "J9", "number": "121"}
    url = jazeera.deeplink("KWI", "DXB", date(2026, 11, 10), date(2026, 11, 17), 2)
    assert "tripType=roundtrip&origin=KWI&destination=DXB&departureDate=2026-11-10&returnDate=2026-11-17" in url
    assert url.endswith("adults=2&children=0&infants=0")


def test_jazeera_relevance(monkeypatch):
    monkeypatch.setattr(jazeera, "network", lambda: {"KWI": ["DXB", "BEY"], "DXB": ["KWI", "BEY"]})
    assert jazeera.relevant(["DXB"], ["BEY"])
    assert not jazeera.relevant(["DXB"], ["LHR"])


def test_flysafair_parse_round_trip():
    data = _load_e("flysafair_jnb_cpt_rt.json")
    bounds = flysafair.parse(data)
    assert [(o, d) for o, d, _ in bounds] == [("JNB", "CPT"), ("CPT", "JNB")]
    out = {j["segments"][0]["number"]: j for j in bounds[0][2]}
    assert out["200"]["total"] == 3540.88  # 2 adults, R 1,770.44 each on the site
    assert out["200"]["fare"] == "Low" and out["200"]["segments"][0]["duration"] == 140
    back = {j["segments"][0]["number"]: j for j in bounds[1][2]}
    assert back["205"]["total"] == 3540.88
    its = combine(_q_e("JNB", "CPT", "2026-11-10", "2026-11-13", adults=2), "flysafair", "FlySafair",
                  bounds[0][2], bounds[1][2], "ZAR", "https://x", flysafair.NAMES)
    assert min(i.price for i in its) == 7081.76
    assert its[0].slices[0].duration_min == 140


def test_flysafair_deeplink_and_relevance(monkeypatch):
    url = flysafair.deeplink("JNB", "CPT", date(2026, 11, 10), date(2026, 11, 13), 2)
    assert url == ("https://www.flysafair.co.za/flight/search?fromCityCode=JNB&toCityCode=CPT"
                   "&departureDateString=2026-11-10&returnDateString=2026-11-13&roundTrip=true&adults=2"
                   "&children=0&infants=0")
    monkeypatch.setattr(flysafair, "network", lambda: {"JNB": ["CPT", "DUR"], "CPT": ["JNB"]})
    assert flysafair.relevant(["JNB"], ["CPT"])
    assert not flysafair.relevant(["CPT"], ["DUR"])


def test_qatar_parse():
    js, cur = qatar_browser.parse(_load_e("qatar_doh_bkk.json"))
    assert cur == "QAR" and len(js) == 3
    assert js[0]["total"] == 2560 and js[0]["fare"] == "ECONOMY_CLASSIC"  # QR834, QAR 2,560 on the site
    assert js[0]["segments"][0]["carrier"] == "QR" and js[0]["segments"][0]["number"] == "834"
    via = js[2]
    assert len(via["segments"]) == 2 and via["segments"][0]["number"] == "840"
    biz, _ = qatar_browser.parse(_load_e("qatar_doh_bkk.json"), "business")
    assert biz and min(j["total"] for j in biz) > js[0]["total"]
    its = combine(_q_e("DOH", "BKK", "2026-11-12"), "qatar", "Qatar Airways", js, None, cur, "https://x")
    assert its[0].slices[0].duration_min == 390


def test_qatar_relevance_and_deeplink(monkeypatch):
    monkeypatch.setattr(_browser, "available", lambda headful=False: True)
    monkeypatch.setattr(qatar_browser, "network", lambda: {"DOH": "QA", "LHR": "GB", "BKK": "TH", "CDG": "FR"})
    assert qatar_browser.relevant(["LHR"], ["BKK"])
    assert qatar_browser.relevant(["DOH"], ["CDG"])
    assert not qatar_browser.relevant(["LHR"], ["CDG"])  # no sense via Doha
    url = qatar_browser.deeplink("DOH", "BKK", date(2026, 11, 12), adults=2)
    assert "tripType=O&fromStation=DOH&toStation=BKK&departing=2026-11-12&bookingClass=E&adults=2" in url


def test_etihad_parse():
    js, cur = etihad_browser.parse(_load_e("etihad_auh_bkk.json"))
    assert cur == "AED"
    by = {j["segments"][0]["number"]: j for j in js}
    assert by["400"]["total"] == 4410 and by["400"]["fare"] == "YBASIC"  # 2 adults, AED 4,410 on the site
    assert by["404"]["total"] == 4790
    biz, _ = etihad_browser.parse(_load_e("etihad_auh_bkk.json"), "business")
    assert {j["fare"] for j in biz} <= {"JVALUE", "JCOMFORT", "JDELUXE"}
    its = combine(_q_e("AUH", "BKK", "2026-11-12", adults=2), "etihad", "Etihad Airways", js, None, cur,
                  "https://x")
    assert its[0].price == 4410 and its[0].slices[0].duration_min == 380


def test_etihad_deeplink():
    url = etihad_browser.deeplink("AUH", "BKK", date(2026, 11, 12), date(2026, 11, 19), 2)
    assert "B_LOCATION=AUH&E_LOCATION=BKK&TRIP_TYPE=R&CABIN=E&TRAVELERS=ADT,ADT" in url
    assert "DATE_1=202611120000&DATE_2=202611190000" in url


def _soon_e(days=45):
    return (date.today() + timedelta(days=days)).isoformat()


@pytest.mark.live
def test_live_jazeera():
    its = jazeera.search(_q_e("KWI", "DXB", _soon_e(), _soon_e(49)))
    assert its and its[0].source == "jazeera" and its[0].currency == "KWD" and its[0].price > 0


@pytest.mark.live
def test_live_flysafair():
    its = flysafair.search(_q_e("JNB", "CPT", _soon_e()))
    assert its and its[0].currency == "ZAR" and its[0].slices[0].segments[0].carrier == "FA"


@pytest.mark.live
def test_live_qatar():
    if not _browser.available():
        pytest.skip("needs Chrome and Playwright")
    its = qatar_browser.search(_q_e("DOH", "BKK", _soon_e()))
    assert its and its[0].currency == "QAR"


@pytest.mark.live
def test_live_etihad():
    if not _browser.available():
        pytest.skip("needs Chrome and Playwright")
    its = etihad_browser.search(_q_e("AUH", "BKK", _soon_e()))
    assert its and its[0].currency == "AED"


# ---- group F ------------------------------------------------------------
def _load_f(name):
    return json.loads((FIXTURES / name).read_text())


def _q_f(o, d, dep, ret=None, **kw):
    return SearchQuery(origins=[o], destinations=[d], departure=date.fromisoformat(dep),
                       return_date=date.fromisoformat(ret) if ret else None, **kw)


def test_spicejet_parse_round_trip():
    # DEL-DXB 5 to 12 Nov 2026, 2 adults. The page showed SG 11 at ₹54,930 per
    # person and a total of ₹142,560 for SG 11 + SG 6 (2 x (54,930 + 16,350)).
    (outs, backs), cur = spicejet_browser.parse(_load_f("spicejet_del_dxb.json"), adults=2)
    assert cur == "INR"
    sg11 = next(j for j in outs if j["segments"][0]["number"] == "11")
    assert sg11["total"] == 2 * 54930 and sg11["fare"] == "RS"
    via = next(j for j in outs if len(j["segments"]) == 2)
    assert [s["carrier"] + s["number"] for s in via["segments"]] == ["SG600", "SG51"]
    sg6 = next(j for j in backs if j["segments"][0]["number"] == "6")
    assert sg6["total"] == 2 * 16350
    its = combine(_q_f("DEL", "DXB", "2026-11-05", "2026-11-12", adults=2), "spicejet", "SpiceJet", [sg11], [sg6],
                  cur, "https://x", spicejet_browser.NAMES)
    assert its[0].price == 142560 and its[0].trip_type == "roundtrip"
    assert its[0].slices[0].duration_min == 235  # 07:45 IST to 10:10 GST


def test_spicejet_deeplink_and_relevance(monkeypatch):
    monkeypatch.setattr(_browser, "available", lambda headful=False: True)
    u = spicejet_browser.deeplink("DEL", "BOM", date(2026, 11, 5), date(2026, 11, 9), 2)
    assert "from=DEL&to=BOM&tripType=2&departure=2026-11-05&return=2026-11-09&adult=2" in u
    assert spicejet_browser.relevant(["DEL"], ["BOM"])
    assert spicejet_browser.relevant(["DXB"], ["COK"])
    assert not spicejet_browser.relevant(["DXB"], ["BKK"])  # abroad to abroad
    assert not spicejet_browser.relevant(["DEL"], ["LHR"])


def test_vietjet_parse():
    # SGN-HAN 5 Nov 2026: the site's reservation panel showed VJ134 Eco at a
    # total of 966,385 VND (fare 384,804 + taxes and fees 581,581).
    js, cur = vietjet_browser.parse(_load_f("vietjet_sgn_han.json"), "SGN", "HAN", date(2026, 11, 5))
    assert cur == "VND"
    vj134 = next(j for j in js if j["segments"][0]["number"] == "134")
    assert vj134["total"] == 966385 and vj134["fare"] == "Eco"
    assert vj134["segments"][0]["departure"] == "2026-11-05T05:00:00+07:00"
    assert vietjet_browser.parse(_load_f("vietjet_sgn_han.json"), "SGN", "HAN", date(2026, 11, 6))[0] == []
    two, _ = vietjet_browser.parse(_load_f("vietjet_sgn_han.json"), "SGN", "HAN", date(2026, 11, 5), adults=2)
    assert next(j for j in two if j["segments"][0]["number"] == "134")["total"] == 2 * 966385


def test_vietjet_deeplink_and_relevance(monkeypatch):
    monkeypatch.setattr(_browser, "available", lambda headful=False: True)
    u = vietjet_browser.deeplink("SGN", "HAN", date(2026, 11, 5))
    assert "departAirport=SGN&arrivalAirport=HAN&departDate=2026-11-05&tripType=oneway&adultCount=1" in u
    assert vietjet_browser.relevant(["SGN"], ["ICN"])
    assert vietjet_browser.relevant(["BKK"], ["CNX"])  # Thai VietJet
    assert not vietjet_browser.relevant(["ICN"], ["NRT"])
    assert not vietjet_browser.relevant(["SGN"], ["JFK"])


def test_akasa_parse():
    # BOM-BLR 20 Oct 2026: the page showed QP1149 Saver at ₹5,050 plus a ₹350
    # convenience fee "added before checkout" (dotREZ fareAmount 5,400).
    js, cur = akasa_browser.parse(_load_f("akasa_bom_blr.json"))
    assert cur == "INR"
    qp1149 = next(j for j in js if j["segments"][0]["number"] == "1149")
    assert qp1149["total"] == 5400 and qp1149["fare"] == "EC" and qp1149["seats"] == 8
    assert qp1149["segments"][0]["departure"] == "2026-10-20T05:35:00+05:30"
    nmi = next(j for j in js if j["segments"][0]["origin"] == "NMI")  # Navi Mumbai, same city search
    assert nmi["segments"][0]["number"] == "2005"
    js2, _ = akasa_browser.parse(_load_f("akasa_bom_blr.json"), adults=3)
    assert next(j for j in js2 if j["segments"][0]["number"] == "1149")["total"] == 3 * 5400


def test_akasa_body_and_relevance(monkeypatch):
    monkeypatch.setattr(_browser, "available", lambda headful=False: True)
    b = akasa_browser.body("BOM", "BLR", date(2026, 10, 20), 2)
    assert b["criteria"][0]["dates"]["beginDate"] == "2026-10-20T00:00:00"
    assert b["passengers"]["types"] == [{"type": "ADT", "count": 2}] and b["taxesAndFees"] == 1
    assert akasa_browser.relevant(["BOM"], ["DOH"])
    assert not akasa_browser.relevant(["DOH"], ["JED"])
    assert not akasa_browser.relevant(["BOM"], ["SIN"])


def _live_day_f(days=45):
    return (date.today() + timedelta(days=days)).isoformat()


def _need_browser_f():
    if not _browser.available():
        pytest.skip("needs Playwright and Google Chrome")


@pytest.mark.live
def test_live_spicejet():
    _need_browser_f()
    its = spicejet_browser.search(_q_f("DEL", "BOM", _live_day_f()))
    assert its and all(i.source == "spicejet" and i.currency == "INR" and i.price > 1000 for i in its)
    assert all(s.carrier == "SG" for i in its for s in i.slices[0].segments)


@pytest.mark.live
def test_live_vietjet():
    _need_browser_f()
    its = vietjet_browser.search(_q_f("SGN", "HAN", _live_day_f()))
    assert its and all(i.source == "vietjet" and i.currency == "VND" and i.price > 100000 for i in its)


@pytest.mark.live
def test_live_akasa_round_trip():
    _need_browser_f()
    its = akasa_browser.search(_q_f("BOM", "BLR", _live_day_f(), _live_day_f(52)))
    assert its and all(i.source == "akasa" and i.trip_type == "roundtrip" and i.currency == "INR" for i in its)


# ---- group G ------------------------------------------------------------
def _q_g(o, d, dep, ret=None, **kw):
    return SearchQuery(origins=[o], destinations=[d], departure=dep, return_date=ret, **kw)


# ---------- Tigerair Taiwan ----------

def test_tigerair_parse():
    data = json.loads((FIXTURES / "tigerair_tpe_nrt.json").read_text())
    dirs, cur = tigerair_browser.parse(data)
    assert cur == "USD" and len(dirs) == 1
    by = {j["segments"][0]["number"]: j for j in dirs[0]}
    # the cheapest family (tigerlight) incl. tax: fare 162.79 + tax 36.56 on the results page cart
    assert by["202"]["total"] == 199.35 and by["202"]["fare"] == "tigerLight"
    assert by["200"]["total"] == 249.19
    assert by["202"]["segments"][0]["departure"] == "2026-11-12T15:35:00"
    two, _ = tigerair_browser.parse(data, adults=2)
    assert {j["total"] for j in two[0]} == {398.7, 498.38}
    its = combine(_q_g("TPE", "NRT", date(2026, 11, 12)), "tigerair", "Tigerair Taiwan", dirs[0], None, cur,
                  "https://x", tigerair_browser.NAMES)
    assert its[0].price == 199.35 and its[0].slices[0].duration_min == 180
    assert its[0].slices[0].segments[0].carrier == "IT" and its[0].seller_kind == "airline"


def test_tigerair_deeplink_and_relevance(monkeypatch):
    monkeypatch.setattr(_browser, "available", lambda headful=False: True)
    monkeypatch.setattr(tigerair_browser, "network", lambda: {"TPE": "TW", "KHH": "TW", "NRT": "JP", "ICN": "KR"})
    url = tigerair_browser.deeplink("TPE", "NRT", date(2026, 11, 12), date(2026, 11, 19), 2)
    assert "outbound=TPE-NRT&departureDate=2026-11-12&returnDate=2026-11-19&adult=2&type=roundTrip" in url
    assert tigerair_browser.relevant(["TPE"], ["NRT"])
    assert tigerair_browser.relevant(["ICN"], ["KHH"])
    assert not tigerair_browser.relevant(["NRT"], ["ICN"])  # every route touches Taiwan
    assert not tigerair_browser.relevant(["TPE"], ["LHR"])


def test_tigerair_station_menu():
    menu = {"data": {"appStationMenuCountries": [
        {"country": {"code2": "TW"}, "stationMenus": [{"station": None, "stationMac": {"macCode": "XX3"}},
                                                      {"station": {"stationCode": "TPE"}}]},
        {"country": {"code2": "JP"}, "stationMenus": [{"station": {"stationCode": "NRT"}}]}]}}
    assert tigerair_browser._stations(menu) == {"TPE": "TW", "NRT": "JP"}


# ---------- ZIPAIR ----------

def test_zipair_parse_local_day():
    data = json.loads((FIXTURES / "zipair_nrt_icn.json").read_text())
    js = zipair_browser.parse(data, date(2026, 11, 12))
    # UTC times: ZG45 23:55Z on the 11th is 08:55 on the 12th in Tokyo; the 12th's 23:55Z is the 13th
    assert [(j["segments"][0]["number"], j["total"]) for j in js] == [("45", 26660.0), ("43", 22660.0)]
    assert js[1]["segments"][0]["departure"] == "2026-11-12T10:55:00+09:00"
    assert js[1]["segments"][0]["arrival"] == "2026-11-12T13:35:00+09:00"
    biz = zipair_browser.parse(data, date(2026, 11, 12), adults=2, cabin="business")
    assert {j["total"] for j in biz} == {2 * (25000 + 6160), 2 * (30000 + 6160)}
    its = combine(_q_g("NRT", "ICN", date(2026, 11, 12)), "zipair", "ZIPAIR", js, None, "JPY", "https://x",
                  zipair_browser.NAMES)
    assert its[0].price == 22660 and its[0].slices[0].duration_min == 160


def test_zipair_parse_transit():
    data = json.loads((FIXTURES / "zipair_icn_nrt_bkk.json").read_text())
    js = zipair_browser.parse(data, date(2026, 11, 12))
    assert len(js) == 1
    j = js[0]
    assert [s["origin"] + s["destination"] for s in j["segments"]] == ["ICNNRT", "NRTBKK"]
    assert j["total"] == 19098 + 2919 + 41000 + 2233  # both legs plus taxes, connection fee 0
    assert j["segments"][1]["departure"] == "2026-11-12T17:00:00+09:00"
    routes = [[{"origin": "ICN", "destination": "NRT"}, {"origin": "NRT", "destination": "BKK"}],
              [{"origin": "ICN", "destination": "NRT"}]]
    assert zipair_browser._routes_param(routes, "ICN", "BKK") == ["ICN,NRT,BKK"]
    assert zipair_browser._routes_param(routes, "ICN", "NRT") == ["ICN,NRT"]


def test_zipair_relevance(monkeypatch):
    monkeypatch.setattr(_browser, "available", lambda headful=False: True)
    assert zipair_browser.relevant(["NRT"], ["LAX"])
    assert not zipair_browser.relevant(["NRT"], ["CDG"])


# ---------- Jeju Air ----------

def test_jejuair_parse():
    frag = (FIXTURES / "jejuair_icn_nrt.html").read_text()
    js, cur = jejuair_browser.parse(frag)
    assert cur == "KRW"
    assert [(j["segments"][0]["number"], j["total"]) for j in js] == [
        ("1181", 131100.0), ("1101", 146100.0), ("1125", 146100.0)]  # the 4th flight is sold out
    s = js[0]["segments"][0]
    assert s["carrier"] == "7C" and s["departure"] == "2026-11-12T07:15:00+09:00"
    js2, _ = jejuair_browser.parse(frag, adults=2)
    assert js2[0]["total"] == 262200.0
    its = combine(_q_g("ICN", "NRT", date(2026, 11, 12)), "jejuair", "Jeju Air", js, None, cur, "https://x",
                  jejuair_browser.NAMES)
    assert its[0].price == 131100 and its[0].slices[0].duration_min == 145


def test_jejuair_form_and_relevance(monkeypatch):
    net = {"ICN": "KR", "CJU": "KR", "NRT": "JP"}
    f = jejuair_browser._form("ICN", "NRT", date(2026, 11, 12), 2, net)
    assert f["domIntType"] == "I" and f["tripRoute"][0]["flightDate"] == "2026-11-12"
    assert f["passengers"] == [{"type": "ADT", "count": "2"}]
    assert jejuair_browser._form("ICN", "CJU", date(2026, 11, 12), 1, net)["domIntType"] == "D"
    monkeypatch.setattr(_browser, "available", lambda headful=False: True)
    monkeypatch.setattr(jejuair_browser, "network", lambda: net)
    assert jejuair_browser.relevant(["ICN"], ["NRT"])
    assert not jejuair_browser.relevant(["ICN"], ["LHR"])


# ---------- live ----------

def _live_day_g(days=45):
    return date.today() + timedelta(days=days)


@pytest.mark.live
@pytest.mark.parametrize("mod,o,d", [
    (tigerair_browser, "TPE", "NRT"),
    (zipair_browser, "NRT", "ICN"),
    (jejuair_browser, "ICN", "NRT"),
])
def test_live_group_g(mod, o, d):
    if not _browser.available():
        pytest.skip("needs Playwright and Google Chrome")
    its = mod.search(_q_g(o, d, _live_day_g()))
    assert its, f"{mod.__name__}: no flights {o}-{d}"
    assert all(i.price > 0 and i.seller_kind == "airline" for i in its)
    assert its[0].slices[0].origin == o and its[0].slices[0].destination == d


# ---- group H ------------------------------------------------------------
def _load_h(name):
    return json.loads((FIXTURES / name).read_text())


def _q_h(o, d, dep="2026-11-12", ret=None, **kw):
    return SearchQuery(origins=[o], destinations=[d], departure=date.fromisoformat(dep),
                       return_date=date.fromisoformat(ret) if ret else None, **kw)


def test_virginaustralia_parse_round_trip():
    (outs, backs), cur = virginaustralia_browser.parse(_load_h("virginaustralia_bne_nan.json"))
    assert cur == "AUD"
    assert [s["carrier"] + s["number"] for s in outs[0]["segments"]] == ["VA175"]
    assert outs[0]["total"] == 380.43 and outs[0]["fare"] == "LT"  # the UI showed "Economy from $380.43"
    direct = next(j for j in backs if len(j["segments"]) == 1)
    assert direct["total"] == 368.63 and direct["segments"][0]["number"] == "178"
    its = combine(_q_h("BNE", "NAN", ret="2026-11-19"), "virginaustralia", "Virgin Australia", outs, backs, cur,
                  "https://x", virginaustralia_browser.NAMES)
    best = min(its, key=lambda i: i.price)
    assert best.price == 749.06 and best.trip_type == "roundtrip"  # = the API's bundle price
    assert best.slices[0].duration_min == 220  # from the GMT offsets
    (outs2, _), _ = virginaustralia_browser.parse(_load_h("virginaustralia_bne_nan.json"), adults=2)
    assert outs2[0]["total"] == 760.86  # Sabre prices per adult
    (biz, _), _ = virginaustralia_browser.parse(_load_h("virginaustralia_bne_nan.json"), cabin="business")
    assert biz and all(j["fare"] == "BU" for j in biz)


def test_virginaustralia_refs_and_relevance(monkeypatch):
    seg = {"@type": "Segment", "@id": "2", "origin": "SYD", "destination": "MEL",
           "departure": "2026-10-20T07:15:00", "arrival": "2026-10-20T08:50:00", "departureGMTOffset": "+11:00",
           "arrivalGMTOffset": "+11:00", "duration": 95, "cabinClass": "Economy",
           "flight": {"flightNumber": 810, "airlineCode": "VA"}}
    price = lambda a: {"alternatives": [[{"amount": a, "currency": "AUD"}]]}  # noqa: E731
    data = {"data": {"bookingAirSearch": {"originalResponse": {"currency": "AUD", "unbundledOffers": [[
        {"brandId": "CH", "cabinClass": "Economy", "total": price(175),
         "itineraryPart": [{"@id": "1", "segments": [seg], "totalDuration": 95}]},
        {"brandId": "LT", "cabinClass": "Economy", "total": price(145), "itineraryPart": [{"@ref": "1"}]},
        {"brandId": "BU", "cabinClass": "Business", "total": price(459), "itineraryPart": [{"@ref": "1"}]},
    ]]}}}}
    (outs,), _ = virginaustralia_browser.parse(data)
    assert len(outs) == 1 and outs[0]["total"] == 145 and outs[0]["fare"] == "LT"
    monkeypatch.setattr(_browser, "available", lambda headful=False: True)
    assert virginaustralia_browser.relevant(["SYD"], ["MEL"])
    assert virginaustralia_browser.relevant(["NAN"], ["BNE"])
    assert not virginaustralia_browser.relevant(["AKL"], ["NAN"])  # no Australian end
    assert not virginaustralia_browser.relevant(["SYD"], ["LAX"])
    url = virginaustralia_browser.deeplink("BNE", "NAN", date(2026, 11, 12), date(2026, 11, 19), 2)
    assert ("journeyType=round-trip" in url and "origin1=NAN&destination1=BNE&date1=11-19-2026" in url
            and "ADT=2" in url)


@pytest.mark.live
def test_virginaustralia_live():
    if not virginaustralia_browser.available():
        pytest.skip("needs Playwright and Chrome")
    dep = date.today() + timedelta(days=30)
    its = virginaustralia_browser.search(_q_h("SYD", "MEL", dep.isoformat(), (dep + timedelta(days=4)).isoformat()))
    assert its and all(i.currency == "AUD" and i.trip_type == "roundtrip" for i in its)
    assert min(i.price for i in its) > 50


def test_airnewzealand_parse_round_trip():
    from flightscout.sources import airnewzealand

    data = _load_h("airnewzealand_akl_zqn.json")
    html = "<script>VUI.pageInit([{name: 'x', data: null}]);VUI.pageInit([" + json.dumps(data) + "]);</script>"
    assert airnewzealand.page_data(html) == data
    (outs, backs), cur = airnewzealand.parse(data, adults=2)
    assert cur == "NZD"
    nz611 = next(j for j in outs if j["segments"][0]["number"] == "611")
    assert nz611["total"] == 778 and nz611["fare"] == "seat"  # 389 per passenger, the site's own total for 2
    conn = next(j for j in outs if len(j["segments"]) == 2)
    assert [s["carrier"] + s["number"] for s in conn["segments"]] == ["NZ541", "NZ5647"]
    its = combine(_q_h("AKL", "ZQN", "2026-11-12", "2026-11-19", adults=2), "airnewzealand", "Air New Zealand",
                  outs, backs, cur, "https://x", airnewzealand.NAMES)
    best = min(its, key=lambda i: i.price)
    assert best.price == 1036 and best.trip_type == "roundtrip"  # (389 + 129) x 2
    assert best.slices[0].duration_min == 115 and best.slices[0].segments[0].duration_min == 115


def test_airnewzealand_deeplink_and_relevance():
    from flightscout.sources import airnewzealand

    url = airnewzealand.deeplink("AKL", "ZQN", date(2026, 11, 12), date(2026, 11, 19), 2)
    assert "searchLegs%5B0%5D.tripStartMonth=NOV&searchLegs%5B0%5D.tripStartDate=12" in url
    assert "searchLegs%5B1%5D.originPoint=ZQN" in url and "tripType=return&adults=2" in url
    assert airnewzealand.relevant(["AKL"], ["WLG"])
    assert not airnewzealand.relevant(["AKL"], ["SYD"])  # international: other booking app


@pytest.mark.live
def test_airnewzealand_live():
    from flightscout.sources import airnewzealand

    dep = date.today() + timedelta(days=30)
    its = airnewzealand.search(_q_h("AKL", "WLG", dep.isoformat(), (dep + timedelta(days=3)).isoformat()))
    assert its and all(i.currency == "NZD" and i.trip_type == "roundtrip" for i in its)
    assert min(i.price for i in its) > 40


# --- Ryanair (fare finder: the cheapest flight of the day) ---------------------

def test_ryanair_parse(monkeypatch):
    from flightscout.sources import ryanair

    monkeypatch.setattr(ryanair, "_airports", lambda: {"STN": "GBP", "DUB": "EUR"})
    day = date.today() + timedelta(days=20)
    fares = {("STN", "DUB"): {"segments": [{"origin": "STN", "destination": "DUB", "departure": f"{day}T06:35:00",
                                            "arrival": f"{day}T07:55:00", "carrier": "FR", "number": "203"}],
                              "total": 69.98, "seats": None, "currency": "GBP"},
             ("DUB", "STN"): {"segments": [{"origin": "DUB", "destination": "STN", "departure": f"{day + timedelta(days=3)}T09:00:00",
                                            "arrival": f"{day + timedelta(days=3)}T10:20:00", "carrier": "FR", "number": "204"}],
                              "total": 50.0, "seats": None, "currency": "EUR"}}
    monkeypatch.setattr(ryanair, "_cheapest", lambda o, d, day, adults, cur: fares.get((o, d)))
    monkeypatch.setattr("flightscout.fx.convert", lambda v, a, b: v * 0.85 if (a, b) == ("EUR", "GBP") else v)
    ow = ryanair.search(SearchQuery(origins=["STN"], destinations=["DUB"], departure=day, adults=2))
    assert len(ow) == 1 and ow[0].price == 69.98 and ow[0].currency == "GBP" and "adults=2" in ow[0].booking_url
    assert ow[0].slices[0].segments[0].flight_number == "203" and ow[0].seller_kind == "airline"
    rt = ryanair.search(SearchQuery(origins=["STN"], destinations=["DUB"], departure=day, return_date=day + timedelta(days=3)))
    assert len(rt) == 1 and rt[0].price == round(69.98 + 42.5, 2) and len(rt[0].slices) == 2
    assert ryanair.search(SearchQuery(origins=["STN"], destinations=["JFK"], departure=day)) == []


@pytest.mark.live
def test_ryanair_live():
    from flightscout.sources import ryanair

    its = ryanair.search(SearchQuery(origins=["STN"], destinations=["DUB"], departure=date.today() + timedelta(days=25)))
    assert its and its[0].slices[0].segments[0].carrier in ("FR", "RK", "AL", "RR") and its[0].price > 5
