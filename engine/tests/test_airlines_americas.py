"""Direct airline sources for the Americas (US low cost and majors, Canada,
Mexico, Caribbean, South America). Offline: parsers against saved responses
in tests/fixtures. Live (FLIGHTSCOUT_LIVE=1): one real search per airline;
browser sources skip when Chrome or Playwright is missing."""

import json
from datetime import date, timedelta

import pytest

from conftest import FIXTURES
from flightscout.models import SearchQuery
from flightscout.sources import (_browser, aerolineas, aeromexico, alaska, arajet, avelo_browser, breeze,
                                 caribbean_browser, caymanairways_browser, frontier, jetblue, porter_browser,
                                 united_browser, westjet_browser, wingo_browser)
from flightscout.sources._airline import combine


# ======== US low cost, Alaska and Hawaiian ========

def _load_a(name):
    return json.loads((FIXTURES / name).read_text())


def _q_a(o, d, dep="2026-11-10", ret=None, **kw):
    return SearchQuery(origins=[o], destinations=[d], departure=date.fromisoformat(dep),
                       return_date=date.fromisoformat(ret) if ret else None, **kw)


def _future_a(days=45):
    return (date.today() + timedelta(days=days)).isoformat()


# Frontier ------------------------------------------------------------------

def test_frontier_parse():
    outs, backs = frontier.parse(_load_a("frontier_den_las.json"))
    assert backs == []
    assert [(j["segments"][0]["number"], j["total"]) for j in outs] == [(2349, 78.98), (3600, 176.58), (2105, 62.36)]
    assert outs[1]["seats"] == 3  # "3 Seats Left!"
    assert outs[0]["duration"] == 122 and len(outs[1]["segments"]) == 2
    outs2, _ = frontier.parse(_load_a("frontier_den_las.json"), adults=2)
    assert outs2[0]["total"] == 157.96
    its = combine(_q_a("DEN", "LAS"), "frontier", "Frontier", outs, None, "USD", "https://x", {"F9": "Frontier"})
    assert its[0].price == 62.36 and its[0].slices[0].segments[0].carrier == "F9"


def test_frontier_flightdata_and_links():
    page = "<script>FlightData = '{&quot;journeys&quot;:[]}';</script>"
    assert frontier.flight_data(page) == {"journeys": []}
    url = frontier.deeplink("DEN", "LAS", date(2026, 11, 10), date(2026, 11, 15), 2)
    assert "o1=DEN&d1=LAS&dd1=Nov%2010%2C%202026&dd2=Nov%2015%2C%202026&r=true&ADT=2" in url
    assert frontier.relevant(["DEN"], ["LAS"])
    assert not frontier.relevant(["OSL"], ["LAS"])


# Breeze --------------------------------------------------------------------

def test_breeze_parse_round_trip():
    outs, backs = breeze.parse(_load_a("breeze_tpa_bdl.json"))
    assert [(j["segments"][0]["number"], j["total"]) for j in outs] == [("1684", 117.0), ("1669", 119.0), ("766", 138.6)]
    # a connection is priced per segment: 101.28 + 15.72
    assert [s["destination"] for s in outs[0]["segments"]] == ["ORF", "BDL"]
    assert outs[1]["duration"] == 161 and outs[1]["segments"][0]["carrier"] == "MX"
    assert len(backs) == 5 and backs[0]["total"] == 89.0
    its = combine(_q_a("TPA", "BDL", ret="2026-11-15"), "breeze", "Breeze Airways", outs, backs, "USD", "https://x")
    assert its[0].price == 117.0 + 89.0 and its[0].trip_type == "roundtrip"


def test_breeze_links_and_relevance():
    url = breeze.deeplink("TPA", "BDL", date(2026, 11, 10), date(2026, 11, 15))
    assert url.startswith("https://www.flybreeze.com/booking/availability?origin=TPA&destination=BDL"
                          "&beginDate=2026-11-10&endDate=2026-11-15&passengers=")
    assert breeze.relevant(["TPA"], ["BDL"])
    assert not breeze.relevant(["TPA"], ["OSL"])


# Avelo ---------------------------------------------------------------------

def test_avelo_parse():
    js = avelo_browser.parse(_load_a("avelo_hvn_mco.json"))
    out, back = js["HVN-MCO"][0], js["MCO-HVN"][0]
    assert out["total"] == 140.75 and out["segments"][0]["number"] == "717"  # Standard, not Avelo PLUS
    assert out["segments"][0]["departure"] == "2026-11-10T06:30:00" and out["duration"] == 170
    assert back["total"] == 223.59
    assert avelo_browser.parse(_load_a("avelo_hvn_mco.json"), adults=2)["HVN-MCO"][0]["total"] == 281.5


def test_avelo_links_and_relevance(monkeypatch):
    monkeypatch.setattr(_browser, "available", lambda headful=False: True)
    assert avelo_browser.deeplink("HVN", "MCO", date(2026, 11, 10), date(2026, 11, 15)) == (
        "https://www.aveloair.com/flight-search/deeplink/searchflights/roundtrip/HVN/MCO/2026-11-10/2026-11-15"
        "/1/0/0/0/?calendar=false")
    assert avelo_browser.relevant(["HVN"], ["MCO"])
    assert not avelo_browser.relevant(["HVN"], ["LHR"])


# JetBlue -------------------------------------------------------------------

def test_jetblue_parse():
    js = jetblue.parse(_load_a("jetblue_jfk_fll.json"))
    assert [(j["segments"][0]["number"], j["total"], j["brand"]) for j in js] == [
        (1, 99.4, "DN"), (2718, 183.33, "DN"), (883, 233.4, "A1")]
    assert js[2]["segments"][1]["carrier"] == "9B" and js[0]["duration"] == 184
    assert jetblue.parse(_load_a("jetblue_jfk_fll.json"), adults=2)[0]["total"] == 198.8
    assert jetblue.parse(_load_a("jetblue_jfk_fll.json"), cabin="business") == []


def test_jetblue_links_and_relevance():
    assert "from=JFK&to=FLL&depart=2026-11-10&return=2026-11-15" in jetblue.deeplink(
        "JFK", "FLL", date(2026, 11, 10), date(2026, 11, 15))
    assert jetblue.relevant(["JFK"], ["FLL"])
    assert not jetblue.relevant(["OSL"], ["TRD"])


# Alaska --------------------------------------------------------------------

def test_alaska_parse():
    js = alaska.parse(_load_a("alaska_sea_lax.json"))
    assert [(j["segments"][0]["number"], j["total"], j["fare"]) for j in js] == [
        (2238, 123.2, "MAIN"), (505, 143.4, "SAVER"), (1306, 143.4, "SAVER")]
    assert js[1]["segments"][0]["departure"] == "2026-11-10T06:00:00-08:00"
    its = combine(_q_a("SEA", "LAX"), "alaska", "Alaska Airlines", js, None, "USD", "https://x", alaska.NAMES)
    assert its[1].slices[0].duration_min == 164  # from the UTC offsets
    assert alaska.parse(_load_a("alaska_sea_lax.json"), cabin="business")[1]["total"] == 698.4


def test_alaska_devalue_stream():
    text = "\n".join([
        json.dumps({"type": "data", "nodes": [{"type": "skip"}, {"type": "data", "data": [{"streamed": 1}, ["Promise", 1]]}]}),
        json.dumps({"type": "chunk", "id": 1, "data": [{"rows": 1, "departureStation": 3}, [2], {"duration": 4}, "SEA", 90]}),
    ])
    assert alaska.results(text) == {"rows": [{"duration": 90}], "departureStation": "SEA"}
    assert alaska.unflatten([{"a": 1, "b": -1}, ["Date", "2026-11-10T00:00:00Z"]]) == {"a": "2026-11-10T00:00:00Z", "b": None}


def test_alaska_links_and_relevance():
    assert alaska.deeplink("SEA", "LAX", date(2026, 11, 10)) == (
        "https://www.alaskaair.com/search/results?A=1&C=0&L=0&O=SEA&D=LAX&OD=2026-11-10&RT=false")
    assert alaska.relevant(["SEA"], ["LAX"]) and alaska.relevant(["HNL"], ["OGG"])
    assert not alaska.relevant(["OSL"], ["LAX"])


# Live ----------------------------------------------------------------------

def _check_live_a(its, source, carrier):
    assert its, f"{source}: no results"
    it = min(its, key=lambda i: i.price)
    assert it.source == source and it.seller_kind == "airline" and it.price > 20
    assert any(s.carrier == carrier for sl in it.slices for s in sl.segments)


@pytest.mark.live
def test_live_frontier():
    _check_live_a(frontier.search(_q_a("DEN", "LAS", _future_a())), "frontier", "F9")


@pytest.mark.live
def test_live_breeze():
    _check_live_a(breeze.search(_q_a("TPA", "BDL", _future_a())), "breeze", "MX")


@pytest.mark.live
def test_live_avelo():
    if not avelo_browser.available():
        pytest.skip("needs Playwright and Chrome")
    _check_live_a(avelo_browser.search(_q_a("HVN", "MCO", _future_a())), "avelo", "XP")


@pytest.mark.live
def test_live_jetblue():
    _check_live_a(jetblue.search(_q_a("JFK", "FLL", _future_a())), "jetblue", "B6")


@pytest.mark.live
def test_live_alaska():
    _check_live_a(alaska.search(_q_a("SEA", "LAX", _future_a())), "alaska", "AS")


# ======== Canada, Mexico and the Caribbean ========

def _load_b(name):
    return json.loads((FIXTURES / name).read_text())


def _q_b(o, d, dep="2026-11-12", ret=None, **kw):
    return SearchQuery(origins=[o], destinations=[d], departure=date.fromisoformat(dep),
                       return_date=date.fromisoformat(ret) if ret else None, **kw)


# ---- Arajet (HTTP) ----

def test_arajet_parse_round_trip_with_bus_leg():
    outs, backs = arajet.parse(_load_b("arajet_ewr_sdq.json"), "EWR", adults=2)
    direct = next(j for j in outs if len(j["segments"]) == 1)
    assert direct["segments"][0]["carrier"] + direct["segments"][0]["number"] == "DM2363"
    assert direct["total"] == round(289.42 * 2, 2)  # ADT price is per passenger
    assert direct["duration"] == 326  # from the GMT times, crosses midnight
    bus = next(j for j in outs if len(j["segments"]) == 2)
    assert bus["segments"][1]["aircraft"] == "BUS" and bus["segments"][1]["carrier"] == "Z9"
    assert {j["segments"][0]["origin"] for j in backs} == {"SDQ"}
    its = combine(_q_b("EWR", "SDQ", ret="2026-11-19", adults=2), "arajet", "Arajet", outs, backs, "USD", "https://x")
    assert its[0].trip_type == "roundtrip" and its[0].currency == "USD"


def test_arajet_relevance_and_deeplink():
    assert arajet.relevant(["EWR"], ["SDQ"])
    assert arajet.relevant(["EWR"], ["LIM"])  # connection via SDQ, listed by the site
    assert not arajet.relevant(["LAX"], ["JFK"])
    url = arajet.deeplink("EWR", "SDQ", date(2026, 11, 12), date(2026, 11, 19), 2)
    assert "origin=EWR&destination=SDQ&from=2026-11-12&to=2026-11-19&adt=2" in url


# ---- Porter (browser) ----

def test_porter_parse():
    outs, backs = porter_browser.parse(_load_b("porter_ytz_yul.json"))
    assert [j["segments"][0]["number"] for j in outs] == ["2471", "2477", "2487"]
    assert outs[0]["total"] == 217.48 and outs[0]["fare"] == "BS" and outs[0]["duration"] == 75
    assert outs[0]["segments"][0]["carrier"] == "PD" and outs[0]["segments"][0]["departure"] == "2026-11-12T14:45:00"
    assert backs[0]["segments"][0]["origin"] == "YUL" and backs[0]["total"] == 230.7
    assert porter_browser.parse(_load_b("porter_ytz_yul.json"), adults=2)[0][0]["total"] == 434.96


def test_porter_relevance_and_deeplink(monkeypatch):
    monkeypatch.setattr(_browser, "available", lambda headful=False: True)
    assert porter_browser.relevant(["YTZ"], ["YUL"])
    assert porter_browser.relevant(["YYZ"], ["LAX"])
    assert not porter_browser.relevant(["LAX"], ["EWR"])  # no US domestic
    url = porter_browser.deeplink("YTZ", "YUL", date(2026, 11, 12), date(2026, 11, 19))
    assert "departStation=YTZ&destination=YUL&depDate=2026-11-12&rtnDate=2026-11-19" in url and "RoundTrip" in url


# ---- WestJet (browser) ----

def test_westjet_parse():
    out_raw, back_raw = _load_b("westjet_yyc_yvr.json")
    outs = westjet_browser.parse(out_raw)
    assert outs[0]["segments"][0]["number"] == "101" and outs[0]["total"] == 109.68 and outs[0]["fare"] == "Basic"
    assert outs[0]["segments"][0]["departure"] == "2026-11-12T07:00:00" and outs[0]["duration"] == 105
    prem = westjet_browser.parse(back_raw, adults=2, cabin="premium")
    assert prem[0]["total"] == round(275.58 * 2, 2)
    its = combine(_q_b("YYC", "YVR", ret="2026-11-19"), "westjet", "WestJet", outs, westjet_browser.parse(back_raw),
                  "CAD", "https://x")
    assert its[0].price == round(109.68 + 99.18, 2)


def test_westjet_relevance(monkeypatch):
    monkeypatch.setattr(_browser, "available", lambda headful=False: True)
    assert westjet_browser.relevant(["YYC"], ["YVR"])
    assert westjet_browser.relevant(["YYZ"], ["CUN"])
    assert not westjet_browser.relevant(["LAX"], ["JFK"])


# ---- Aeromexico (HTTP) ----

def test_aeromexico_parse_by_fare_type():
    outs, backs = aeromexico.parse(_load_b("aeromexico_mex_cun.json"))
    am504 = {t: j["total"] for t, js in outs.items() for j in js if j["segments"][0]["number"] == 504}
    assert am504 == {"CLASSIC": 444.83, "FLEX": 476.15, "BASIC": 435.55}  # AM Plus Basic is the cheapest
    assert "PREMIER" not in {j["fare"].split("_")[0] for js in outs.values() for j in js}
    biz, _ = aeromexico.parse(_load_b("aeromexico_mex_cun.json"), cabin="business")
    assert all(j["fare"].startswith("PREMIER") for js in biz.values() for j in js)
    assert backs["BASIC"][1]["segments"][0]["origin"] == "CUN"


def test_aeromexico_round_trip_pairs_same_fare_type(monkeypatch):
    monkeypatch.setattr(aeromexico, "_search", lambda *a: _load_b("aeromexico_mex_cun.json"))
    its = aeromexico.search(_q_b("MEX", "CUN", ret="2026-11-19"))
    best = min(its, key=lambda i: i.price)
    # cheapest pair: AM508 Main Classic 365.95 + AM505 Main Classic 120.67 (Classic with Classic)
    assert best.price == 486.62 and best.slices[0].segments[0].flight_number == "508"
    # a Basic outbound is never paired with a Classic return
    am512 = [i for i in its if i.slices[0].segments[0].flight_number == "512" and i.slices[1].segments[0].flight_number == "505"]
    assert min(i.price for i in am512) == round(min(437.87 + 120.67, 428.59 + 110.23), 2)
    assert len({i.flight_key for i in its}) == len(its)
    assert aeromexico.relevant(["MEX"], ["CUN"]) and aeromexico.relevant(["LAX"], ["BOG"])
    assert not aeromexico.relevant(["LAX"], ["JFK"])
    assert "itinerary=MEX_CUN_2026-11-12.CUN_MEX_2026-11-19" in its[0].booking_url


# ---- Caribbean Airlines (browser) ----

def test_caribbean_parse_recommendations():
    bounds, prices = caribbean_browser.parse(_load_b("caribbean_pos_jfk.json"))
    assert [s["number"] for s in bounds[0][0]["segments"]] == ["550"]
    assert bounds[0][0]["segments"][0]["departure"] == "2026-11-12T19:30:00"
    assert bounds[0][0]["duration"] == 320
    assert min(prices, key=lambda x: x[2]) == (0, 0, 615.23)


def test_caribbean_search_offline(monkeypatch):
    monkeypatch.setattr(_browser, "available", lambda headful=False: True)
    monkeypatch.setattr(caribbean_browser, "_fetch", lambda *a: _load_b("caribbean_pos_jfk.json"))
    its = caribbean_browser.search(_q_b("POS", "JFK", ret="2026-11-19"))
    assert its[0].price == 615.23 and its[0].trip_type == "roundtrip"
    assert [s.flight_number for s in its[0].slices[1].segments] == ["423"]
    assert caribbean_browser.relevant(["POS"], ["JFK"]) and not caribbean_browser.relevant(["JFK"], ["LAX"])


# ---- Cayman Airways (browser) ----

def test_caymanairways_parse_resolves_refs():
    outs, backs = caymanairways_browser.parse(_load_b("caymanairways_gcm_mia.json"))
    assert [(j["segments"][0]["number"], j["total"], j["fare"]) for j in outs] == [(102, 237.55, "EL"), (106, 237.55, "EL")]
    assert backs[0]["segments"][0]["origin"] == "MIA" and backs[0]["total"] == 138.5  # from an @ref
    its = combine(_q_b("GCM", "MIA", ret="2026-11-19"), "caymanairways", "Cayman Airways", outs, backs, "USD", "https://x")
    assert its[0].price == 376.05 and its[0].slices[0].duration_min == 95
    biz, _ = caymanairways_browser.parse(_load_b("caymanairways_gcm_mia.json"), cabin="business")
    assert biz[0]["total"] == 430.55


def test_caymanairways_relevance_and_deeplink(monkeypatch):
    monkeypatch.setattr(_browser, "available", lambda headful=False: True)
    assert caymanairways_browser.relevant(["GCM"], ["MIA"]) and not caymanairways_browser.relevant(["MIA"], ["JFK"])
    url = caymanairways_browser.deeplink("GCM", "MIA", date(2026, 11, 12), date(2026, 11, 19))
    assert "journeyType=round-trip" in url and "date=11-12-2026" in url and "date1=11-19-2026" in url


# ---- live ----

def _live_day_b(days=45):
    return (date.today() + timedelta(days=days)).isoformat()


def _check_live_b(its, currency):
    assert its, "no itineraries"
    assert all(i.price > 0 and i.currency == currency and i.seller_kind == "airline" for i in its)


@pytest.mark.live
def test_live_arajet():
    _check_live_b(arajet.search(_q_b("EWR", "SDQ", _live_day_b())), "USD")


@pytest.mark.live
def test_live_aeromexico():
    _check_live_b(aeromexico.search(_q_b("MEX", "CUN", _live_day_b())), "USD")


@pytest.mark.live
@pytest.mark.parametrize("mod,o,d,cur", [
    (porter_browser, "YTZ", "YUL", "CAD"), (westjet_browser, "YYC", "YVR", "CAD"),
    (caribbean_browser, "POS", "JFK", "USD"), (caymanairways_browser, "GCM", "MIA", "USD"),
])
def test_live_browser_airlines(mod, o, d, cur):
    if not mod.available():
        pytest.skip("needs Playwright and Google Chrome")
    _check_live_b(mod.search(_q_b(o, d, _live_day_b())), cur)


# ======== South America ========

def _load_c(name):
    return json.loads((FIXTURES / name).read_text())


def _q_c(o, d, dep="2026-11-10", ret=None, **kw):
    return SearchQuery(origins=[o], destinations=[d], departure=date.fromisoformat(dep),
                       return_date=date.fromisoformat(ret) if ret else None, **kw)


def _future_c(days=45):
    return date.today() + timedelta(days=days)


# Aerolíneas Argentinas

def test_aerolineas_parse_round_trip():
    bounds, cur = aerolineas.parse(_load_c("aerolineas_aep_cor.json"))
    assert cur == "ARS" and len(bounds) == 2
    outs, backs = bounds
    first = next(j for j in outs if j["segments"][0]["number"] == 1526)
    assert first["total"] == 57352 and first["fare"] == "Base"  # cheapest brand, what the page shows
    assert first["segments"][0]["origin"] == "AEP" and first["segments"][0]["carrier"] == "AR"
    ret = next(j for j in backs if j["segments"][0]["number"] == 1551)
    assert ret["total"] == 80883
    its = combine(_q_c("AEP", "COR", "2026-11-10", "2026-11-17"), "aerolineas", "Aerolíneas Argentinas", outs, backs,
                  cur, "https://x", aerolineas.NAMES)
    assert its[0].price == 57352 + 80883 and its[0].trip_type == "roundtrip"
    assert its[0].slices[0].duration_min == 90
    two, _ = aerolineas.parse(_load_c("aerolineas_aep_cor.json"), adults=2)
    assert next(j for j in two[0] if j["segments"][0]["number"] == 1526)["total"] == 2 * 57352


def test_aerolineas_deeplink_and_relevance():
    url = aerolineas.deeplink("AEP", "COR", date(2026, 11, 10), date(2026, 11, 17), 2)
    assert "adt=2" in url and "flightType=ROUND_TRIP" in url
    assert "leg=AEP-COR-20261110&leg=COR-AEP-20261117" in url
    assert aerolineas.relevant(["AEP"], ["COR"])
    assert aerolineas.relevant(["EZE"], ["MIA"])
    assert not aerolineas.relevant(["SCL"], ["LIM"])  # no Argentina end
    assert not aerolineas.relevant(["EZE"], ["NRT"])


# Wingo

def test_wingo_parse_round_trip():
    outs, backs, cur = wingo_browser.parse(_load_c("wingo_bog_ctg.json"), date(2026, 11, 10), date(2026, 11, 17))
    assert cur == "COP"
    assert [j["segments"][0]["number"] for j in outs] == ["7216", "7226", "7230"]
    assert outs[0]["total"] == 177805 and outs[0]["segments"][0]["carrier"] == "P5"
    assert outs[0]["duration"] == 92
    assert all(j["total"] == 603317 for j in backs) and backs[0]["segments"][0]["origin"] == "CTG"
    its = combine(_q_c("BOG", "CTG", "2026-11-10", "2026-11-17"), "wingo", "Wingo", outs, backs, cur, "https://x",
                  wingo_browser.NAMES)
    assert its[0].price == 177805 + 603317 and its[0].trip_type == "roundtrip"
    # the JSON also carries neighbouring days: only the asked date is used
    ow, _, _ = wingo_browser.parse(_load_c("wingo_bog_ctg.json"), date(2026, 11, 9))
    assert ow and all(j["segments"][0]["departure"].startswith("2026-11-09") for j in ow)


def test_wingo_deeplink_and_relevance(monkeypatch):
    monkeypatch.setattr(_browser, "available", lambda headful=False: True)
    assert wingo_browser.deeplink("BOG", "CTG", date(2026, 11, 10)) == \
        "https://booking.wingo.com/es/search/BOG/CTG/2026-11-10/1/0/0/1/COP/0/0"
    assert wingo_browser.deeplink("BLB", "BOG", date(2026, 11, 10), date(2026, 11, 17)) == \
        "https://booking.wingo.com/es/search/BLB/BOG/2026-11-10/2026-11-17/1/0/0/0/USD/0/0"
    assert wingo_browser.relevant(["BOG"], ["CUN"])
    assert not wingo_browser.relevant(["BOG"], ["PTY"])  # Wingo flies to BLB, not PTY
    assert not wingo_browser.relevant(["SCL"], ["LIM"])


# Live

@pytest.mark.live
def test_live_aerolineas():
    its = aerolineas.search(_q_c("AEP", "COR", str(_future_c())))
    assert its and all(i.currency == "ARS" and i.price > 1000 for i in its)
    assert all(i.seller == "Aerolíneas Argentinas" and i.seller_kind == "airline" for i in its)


@pytest.mark.live
def test_live_wingo():
    if not wingo_browser.available():
        pytest.skip("needs Playwright and Chrome")
    its = wingo_browser.search(_q_c("BOG", "CTG", str(_future_c())))
    assert its and all(i.currency == "COP" and i.price > 10000 for i in its)
    assert its[0].slices[0].segments[0].carrier == "P5"


# ======== United ========

def _q_d(o, d, dep="2026-11-12", ret=None, **kw):
    return SearchQuery(origins=[o], destinations=[d], departure=date.fromisoformat(dep),
                       return_date=date.fromisoformat(ret) if ret else None, **kw)



# ---- United (headless Chrome) ----

def test_united_parse():
    sse = (FIXTURES / "united_ewr_ord.sse").read_text()
    js = united_browser.parse(sse)
    by = {tuple(s["number"] for s in j["segments"]): j for j in js}
    assert by[("530",)]["total"] == 149 and by[("530",)]["fare"] == "ECO-BASIC"  # UI: $149
    assert by[("254",)]["total"] == 307  # no Basic on this flight
    assert by[("1870", "1773")]["segments"][1]["origin"] == "CLE"
    first = {tuple(s["number"] for s in j["segments"]): j for j in united_browser.parse(sse, "first")}
    assert first[("530",)]["total"] == 1647  # UI: $1,647
    its = combine(_q_d("EWR", "ORD", "2026-11-13"), "united", "United Airlines", js, None, "USD", "https://x")
    nonstop = next(i for i in its if i.slices[0].segments[0].flight_number == "530")
    assert nonstop.slices[0].duration_min == 168  # from the UTC offsets (EWR -5, ORD -6)


def test_united_deeplink_and_relevance(monkeypatch):
    monkeypatch.setattr(_browser, "available", lambda headful=False: True)
    assert united_browser.relevant(["SFO"], ["LAX"]) and united_browser.relevant(["FRA"], ["EWR"])
    assert not united_browser.relevant(["FRA"], ["CDG"])
    url = united_browser.deeplink("DEN", "IAH", date(2026, 11, 19), date(2026, 11, 23))
    assert "f=DEN&t=IAH&d=2026-11-19&r=2026-11-23&tt=0" in url


@pytest.mark.live
def test_united_live():
    if not _browser.available():
        pytest.skip("needs Playwright and Chrome")
    dep = (date.today() + timedelta(days=45)).isoformat()
    its = united_browser.search(_q_d("EWR", "ORD", dep))
    assert its and all(i.source == "united" and i.currency == "USD" for i in its)
    assert 30 < min(i.price for i in its) < 2000
