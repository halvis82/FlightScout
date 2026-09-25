"""Google sometimes embeds the cheapest outbounds without a price (depends on
the asking IP). search() must still list them, priced from the page's own
GetShoppingResults response, instead of silently dropping them."""

import copy
import json
from datetime import date
from pathlib import Path

from fli.search._decoders import parse_flight_row

from flightscout import cache
from flightscout.models import SearchQuery
from flightscout.sources import google

ROWS = json.loads((Path(__file__).parent / "fixtures" / "google_rows_san_osl.json").read_text())


def _unpriced(row):
    r = copy.deepcopy(row)
    r[1][0] = []  # Google's "no shopping list price" marker
    return r


def test_unpriced_outbound_is_filled_and_listed(monkeypatch):
    cheap = parse_flight_row(ROWS[0])
    assert cheap.price == 727.0
    blank = parse_flight_row(_unpriced(ROWS[0]))
    assert blank.price is None
    others = [parse_flight_row(r) for r in ROWS[1:]]

    def fake_search(self, filters, top_n, currency):
        self.outbounds, self.filters = [blank, *others], filters
        return []

    monkeypatch.setattr(google._DiverseSearch, "search", fake_search)
    monkeypatch.setattr(google, "_page_rows", lambda f, c: google._priced(ROWS, parse_flight_row))
    monkeypatch.setenv("FLIGHTSCOUT_NO_CACHE", "1")
    monkeypatch.setattr(cache, "put", lambda *a, **k: None)
    q = SearchQuery(origins=["SAN"], destinations=["OSL"], departure=date(2026, 11, 10),
                    return_date=date(2026, 11, 20), currency="USD", sources=["google"])
    its = google.search(q)
    best = min(its, key=lambda i: i.price)
    assert best.price == 727.0 and best.return_pending
    assert best.slices[0].segments[0].carrier == "DL"


def test_narrow_search_skips_page_rows_when_all_priced(monkeypatch):
    called = []
    monkeypatch.setattr(google, "_page_rows", lambda f, c: called.append(1) or [])
    others = [parse_flight_row(r) for r in ROWS]

    def fake_search(self, filters, top_n, currency):
        self.outbounds, self.filters = others, filters
        return []

    monkeypatch.setattr(google._DiverseSearch, "search", fake_search)
    monkeypatch.setenv("FLIGHTSCOUT_NO_CACHE", "1")
    monkeypatch.setattr(cache, "put", lambda *a, **k: None)
    q = SearchQuery(origins=["SAN"], destinations=["OSL"], departure=date(2026, 11, 10),
                    return_date=date(2026, 11, 20), currency="USD", sources=["google"])
    assert len(google.search(q, wide=False)) == 3
    assert not called


def test_one_way_adds_rows_only_the_page_list_has(monkeypatch):
    rows = [parse_flight_row(r) for r in ROWS]
    monkeypatch.setattr(google._DiverseSearch, "search", lambda self, filters, top_n, currency: rows[1:])
    monkeypatch.setattr(google, "_page_rows", lambda f, c: rows)
    monkeypatch.setenv("FLIGHTSCOUT_NO_CACHE", "1")
    monkeypatch.setattr(cache, "put", lambda *a, **k: None)
    q = SearchQuery(origins=["SAN"], destinations=["OSL"], departure=date(2026, 11, 10), currency="USD",
                    sources=["google"])
    its = google.search(q)
    assert len(its) == 3  # the two embedded rows plus the one only the page list had, no duplicates
    assert min(i.price for i in its) == 727.0


def test_top_departing_flights_are_marked_in_google_order(monkeypatch):
    # ds:1 [2] holds Google's "Top departing flights", [3] the other flights
    inner = [None, None, [[ROWS[1]]], [[ROWS[0], ROWS[2]]]]
    monkeypatch.setattr(google._fli_flights, "fetch_payload", lambda client, url: inner)
    google._hook_page_fetch()
    google._fli_flights.fetch_payload(None, "u")
    top_key = google._legs_key(parse_flight_row(ROWS[1]))
    assert google._TOP["u"] == {top_key}

    class C:
        rank = {top_key: 0}
        top = {top_key}

    assert google._ranked(C, parse_flight_row(ROWS[1])) == {"google_rank": 0, "google_top": True}
    assert google._ranked(C, parse_flight_row(ROWS[0])) == {"google_rank": None, "google_top": False}


def test_extension_list_is_requested_then_used(monkeypatch):
    from flightscout import browser_fetch

    filters = object()
    monkeypatch.setattr("fli.search._tfs.build_tfs", lambda f: "T")
    monkeypatch.setattr(google._fli_flights, "page_url", lambda tfs, cur, *a: f"https://www.google.com/travel/flights?tfs={tfs}")
    url = "list:https://www.google.com/travel/flights?tfs=T"
    try:
        with browser_fetch.browser_pages({}):
            assert google._page_rows(filters, "USD") == []
        raise AssertionError("expected NeedPages")
    except browser_fetch.NeedPages as e:
        assert e.urls == [url]
    with browser_fetch.browser_pages({url: ROWS}):
        rows = google._page_rows(filters, "USD")
    assert sorted(r.price for r in rows) == sorted(parse_flight_row(r).price for r in ROWS)
