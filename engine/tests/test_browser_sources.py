"""Direct airline sources read through a real Chrome (sources/_browser.py).
Offline: parsers against saved responses. Live (-m live): one real search per
airline, skipped when Chrome or Playwright is missing."""

import json
from datetime import date, timedelta

import pytest

from conftest import FIXTURES
from flightscout.models import SearchQuery
from flightscout.sources import (_browser, allegiant_browser, norwegian_browser, southwest_browser,
                                 transavia_browser, vivaaerobus_browser)
from flightscout.sources._airline import combine


def load(name):
    return json.loads((FIXTURES / name).read_text())


def q(o, d, dep="2026-11-06", ret=None, **kw):
    return SearchQuery(origins=[o], destinations=[d], departure=date.fromisoformat(dep),
                       return_date=date.fromisoformat(ret) if ret else None, **kw)


def test_transavia_parse_round_trip():
    outs, backs = transavia_browser.parse(load("transavia_ams_bcn.json"))
    assert [x["segments"][0]["number"] for x in outs] == ["5131", "5133"]
    assert outs[1]["total"] == 103 and outs[1]["segments"][0]["carrier"] == "HV"
    assert len(backs) == 1 and backs[0]["segments"][0]["origin"] == "BCN"
    its = combine(q("AMS", "BCN", "2026-11-13", "2026-11-17"), "transavia", "Transavia", outs, backs, "EUR",
                  "https://x", transavia_browser.NAMES)
    assert its[0].price == 103 + 83 and its[0].trip_type == "roundtrip"
    assert its[0].slices[0].duration_min == 135  # from the UTC offsets
    outs2, _ = transavia_browser.parse(load("transavia_ams_bcn.json"), adults=2)
    assert outs2[1]["total"] == 206  # the API prices one passenger


def test_transavia_deeplink_and_relevance(monkeypatch):
    monkeypatch.setattr(_browser, "available", lambda headful=False: True)
    url = transavia_browser.deeplink("ORY", "LIS", date(2026, 11, 5), date(2026, 11, 12), 2)
    assert "ds=ORY&as=LIS&od=5&om=11&oy=2026&r=True&id=12&im=11&iy=2026&ap=2" in url
    assert transavia_browser.relevant(["ORY"], ["OPO"])
    assert transavia_browser.relevant(["LIS"], ["AMS"])
    assert not transavia_browser.relevant(["LIS"], ["MAD"])  # no Transavia base
    assert not transavia_browser.relevant(["ORY"], ["JFK"])


def test_norwegian_parse():
    js = norwegian_browser.parse(load("norwegian_osl_bcn.json"))[0]
    cur = norwegian_browser.parse(load("norwegian_osl_bcn.json"))[1]
    assert cur == "EUR" and len(js) == 2
    via = next(j for j in js if len(j["segments"]) == 2)
    assert via["total"] == 148.71 and via["fare"] == "LOWFARE"
    assert [s["carrier"] + s["number"] for s in via["segments"]] == ["DY820", "D85503"]
    direct = next(j for j in js if len(j["segments"]) == 1)
    assert direct["total"] == 166.76
    its = combine(q("OSL", "BCN", "2026-11-05"), "norwegian", "Norwegian", js, None, cur, "https://x")
    assert its[0].slices[0].duration_min == via["duration"] == 345


def test_norwegian_relevance(monkeypatch):
    monkeypatch.setattr(_browser, "available", lambda headful=False: True)
    assert norwegian_browser.relevant(["OSL"], ["BCN"])
    assert norwegian_browser.relevant(["LGW"], ["CPH"])
    assert not norwegian_browser.relevant(["LGW"], ["BCN"])  # no Nordic end
    monkeypatch.setattr(_browser, "available", lambda headful=False: False)
    assert not norwegian_browser.relevant(["OSL"], ["BCN"])


def test_southwest_parse_round_trip():
    outs, backs = southwest_browser.parse(load("southwest_san_den.json"))
    assert len(outs) == 2 and len(backs) == 2
    a = outs[0]
    assert a["total"] == 108.40 and a["fare"] == "WGA" and a["segments"][0]["number"] == "3700"
    its = combine(q("SAN", "DEN", "2026-11-06", "2026-11-10"), "southwest", "Southwest", outs, backs, "USD", "u")
    assert its[0].price == round(108.40 + 98.40, 2)
    assert southwest_browser.parse(load("southwest_san_den.json"), adults=3)[0][0]["total"] == 325.2


def test_southwest_deeplink_and_relevance(monkeypatch):
    monkeypatch.setattr(_browser, "available", lambda headful=False: True)
    u = southwest_browser.deeplink("SAN", "DEN", date(2026, 11, 6), date(2026, 11, 10))
    assert "originationAirportCode=SAN" in u and "tripType=roundtrip" in u and "returnDate=2026-11-10" in u
    assert southwest_browser.relevant(["SAN"], ["LAS"])
    assert not southwest_browser.relevant(["SAN"], ["JFK"])


def test_vivaaerobus_parse_skips_points_fares():
    bounds, cur = vivaaerobus_browser.parse(load("vivaaerobus_mty_tij.json"))
    assert cur == "USD" and len(bounds) == 2
    out = bounds[0]
    assert [j["total"] for j in out] == [78.8, 114.93]  # 60.30 is a Doters points fare
    assert out[0]["duration"] == 172 and out[0]["segments"][0]["carrier"] == "VB"
    assert vivaaerobus_browser.deeplink("MTY", "TIJ", date(2026, 11, 6), date(2026, 11, 10), 2).endswith(
        "itineraryCode=MTY_TIJ_20261106.TIJ_MTY_20261110&passengers=A2")


def test_allegiant_parse_round_trip_and_routes(monkeypatch):
    outs, backs = allegiant_browser.parse(load("allegiant_las_bli.json"))
    assert [(x["segments"][0]["number"], x["total"]) for x in outs] == [("282", 41), ("272", 55)]
    assert backs[0]["segments"][0]["origin"] == "BLI" and backs[0]["segments"][0]["carrier"] == "G4"
    its = combine(q("LAS", "BLI", "2026-11-06", "2026-11-09"), "allegiant", "Allegiant", outs, backs, "USD", "u")
    assert its[0].price == 41 + 44
    assert allegiant_browser.parse(load("allegiant_las_bli.json"), adults=2)[0][0]["total"] == 82
    monkeypatch.setattr(_browser, "available", lambda headful=False: True)
    assert allegiant_browser.relevant(["LAS"], ["BLI"])
    assert not allegiant_browser.relevant(["LAS"], ["JFK"])  # not an Allegiant route
    assert "tt=ROUNDTRIP&o=LAS&d=BLI" in allegiant_browser.deeplink("LAS", "BLI", date(2026, 11, 6), date(2026, 11, 9))


def test_search_adds_browser_sources_only_with_a_browser(monkeypatch):
    from flightscout import search as s

    calls = []
    for name in s.BROWSER_SOURCES:
        monkeypatch.setitem(s.SOURCES, name, lambda qq, n=name: calls.append(n) or [])
    for name in [n for n in s.SOURCES if n not in s.BROWSER_SOURCES]:  # stay offline
        monkeypatch.setitem(s.SOURCES, name, lambda qq: [])
    monkeypatch.setattr(_browser, "available", lambda headful=False: False)
    s.search(q("SAN", "LAS"))
    assert calls == []
    monkeypatch.setattr(_browser, "available", lambda headful=False: True)
    s.search(q("SAN", "LAS"))
    assert sorted(calls) == sorted(s.BROWSER_SOURCES)
    calls.clear()
    s.search(q("SAN", "LAS", sources=["google"]))  # an explicit Google only search stays Google only
    assert calls == []


D = date.today() + timedelta(days=42)
LIVE = [
    ("transavia", transavia_browser, "ORY", "LIS", False),
    ("norwegian", norwegian_browser, "OSL", "BCN", False),
    ("southwest", southwest_browser, "SAN", "LAS", False),
    ("vivaaerobus", vivaaerobus_browser, "MEX", "CUN", True),
    ("allegiant", allegiant_browser, "LAS", "BLI", True),
]


@pytest.mark.live
@pytest.mark.parametrize("name,mod,o,d,headful", LIVE, ids=[x[0] for x in LIVE])
def test_live_browser_source(name, mod, o, d, headful):
    if not _browser.available(headful):
        pytest.skip("needs Playwright + Google Chrome" + (" + a display" if headful else ""))
    its = []
    for k in range(3):  # Allegiant flies some routes only a few days a week
        if its := mod.search(q(o, d, str(D + timedelta(days=k)))):
            break
    assert its, f"{name}: no results for {o}-{d} around {D}"
    assert all(i.source == name and i.seller_kind == "airline" and i.price > 0 for i in its)
    assert all(i.booking_url.startswith("https://") for i in its)
    assert all(i.slices[0].origin == o and i.slices[0].destination == d for i in its)


def test_disable_switch_and_blocked_source_pause(monkeypatch):
    import time as _t

    from flightscout import search as s

    monkeypatch.setattr(s._browser, "available", lambda headful=False: False)
    monkeypatch.setenv("FLIGHTSCOUT_DISABLE", "otas,kiwi")
    got = s.expand_sources(["google", "kiwi", "airlines", "otas"])
    assert "kiwi" not in got and not set(got) & set(s.OTAS) and "google" in got and "jetblue" in got
    monkeypatch.delenv("FLIGHTSCOUT_DISABLE")

    s._cool.clear()
    s._note("booking", RuntimeError("search page HTTP 429"))
    assert s._cooling("booking") > 500
    s._note("booking", RuntimeError("HTTP 403"))  # a repeat block doubles the pause
    assert s._cooling("booking") > 1100
    s._note("google", RuntimeError("429"))  # Google has its own fallback
    assert not s._cooling("google")
    s._note("booking", None)  # success clears it
    assert not s._cooling("booking")
    s._cool.clear()
    assert _t.time()


def test_booking_sites_split_fast_and_slow(monkeypatch):
    from flightscout import search as s

    monkeypatch.setattr(s._browser, "available", lambda headful=False: True)
    fast, slow, both = s.expand_sources(["otas_fast"]), s.expand_sources(["otas_slow"]), s.expand_sources(["otas"])
    assert set(fast) == s.OTAS_FAST and not set(fast) & set(slow)
    assert set(fast) | set(slow) == set(both) and "ita" in slow and "tripcom" in slow


def test_every_direct_source_has_airline_codes_and_the_web_map_is_current():
    import json
    from pathlib import Path

    from flightscout import search as s

    missing = [n for n in list(s.AIRLINES) + list(s.BROWSER_SOURCES) if n not in s.AIRLINE_CODES]
    assert not missing, f"add these to AIRLINE_CODES in search.py: {missing}"
    web = json.loads((Path(__file__).resolve().parents[2] / "web" / "src" / "lib" / "direct-airlines.json").read_text())
    for name, codes in s.AIRLINE_CODES.items():
        if name not in s.HEADFUL_ONLY:
            assert all(c in web for c in codes), f"run scripts/gen_sources_doc.py ({name})"
