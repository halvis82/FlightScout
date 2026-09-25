"""Priceline (priceline.com server rendered search results). Offline: the
parser against a trimmed saved page. Live (-m live): one real search."""

import json
from datetime import date, timedelta

import pytest

from conftest import FIXTURES
from flightscout.models import SearchQuery
from flightscout.sources import priceline


def page():
    return priceline.state_from_html((FIXTURES / "priceline_lax_jfk.html").read_text())


def test_state_from_html():
    st = page()
    assert len(st["listings"]["response"]) == 3
    assert priceline.state_from_html("<html>nothing here</html>") is None


def test_parse_one_way_filters_nearby_airports():
    its = priceline.parse(page(), ["LAX"], ["JFK"], url="u")
    got = {i.slices[0].segments[0].carrier + i.slices[0].segments[0].flight_number: i for i in its}
    assert "DL665" not in got  # leaves from Ontario (ONT), Priceline's nearby airport
    assert set(got) == {"AS668", "B61524", "DL938"}  # DL938 comes from the recommended block
    a = got["AS668"]
    assert a.price == 224.2 and a.currency == "USD" and a.source == "priceline"
    assert a.seller == "Priceline" and a.seller_kind == "ota" and not a.return_pending
    assert [s.carrier + s.flight_number for s in a.slices[0].segments] == ["AS668", "AS18"]
    assert a.slices[0].stops == 1 and a.slices[0].segments[0].carrier_name == "Alaska Airlines"
    assert "Priceline cheapest fare brand: Saver." in a.warnings
    assert a.baggage == {"hand": 1, "checked": 0}
    b = got["B61524"]
    assert b.price == 248.4 and b.slices[0].stops == 0 and b.slices[0].duration_min > 300
    # without airport filters the Ontario flight is kept; duplicates are dropped
    all_ = priceline.parse(page())
    assert len(all_) == 4 and any(i.slices[0].origin == "ONT" for i in all_)
    assert priceline.parse(page(), ["LAX"], ["JFK"], max_stops=0)[0].slices[0].stops == 0
    assert {i.slices[0].segments[0].flight_number for i in priceline.parse(page(), ["LAX"], ["JFK"], max_stops=0)} \
        == {"1524", "938"}


def test_parse_round_trip_is_return_pending():
    st = json.loads((FIXTURES / "priceline_lax_jfk_rt.json").read_text())
    its = priceline.parse(st, ["LAX"], ["JFK"], round_trip=True)
    assert len(its) == 1
    i = its[0]
    assert i.return_pending and i.trip_type == "roundtrip" and len(i.slices) == 1
    assert i.price == 373.1


def test_deeplink():
    assert priceline.deeplink("LAX", "JFK", date(2026, 11, 6)) == \
        "https://www.priceline.com/m/fly/search/LAX-JFK-20261106/?cabin-class=ECO&num-adults=1"
    assert priceline.deeplink("LAX", "JFK", date(2026, 11, 6), date(2026, 11, 10), 2, "business") == \
        "https://www.priceline.com/m/fly/search/LAX-JFK-20261106/JFK-LAX-20261110/?cabin-class=BUS&num-adults=2"


def test_search_uses_cache_and_url(monkeypatch):
    urls = []
    monkeypatch.setattr(priceline, "_fetch", lambda u: urls.append(u) or page())
    q = SearchQuery(origins=["LAX"], destinations=["JFK"], departure=date.today() + timedelta(days=40))
    its = priceline.search(q)
    assert len(its) == 3 and urls == [its[0].booking_url]


@pytest.mark.live
def test_live_priceline():
    d = date.today() + timedelta(days=42)
    its = priceline.search(SearchQuery(origins=["LAX"], destinations=["JFK"], departure=d))
    assert len(its) >= 5, "priceline: too few results for LAX-JFK"
    assert all(i.source == "priceline" and i.seller_kind == "ota" and i.price > 0 for i in its)
    assert all(i.slices[0].origin == "LAX" and i.slices[0].destination == "JFK" for i in its)
    assert all(i.slices[0].departure.date() == d for i in its)
