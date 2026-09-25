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
    monkeypatch.setattr(google, "_browser_prices", lambda f, c: google._priced(ROWS, parse_flight_row))
    monkeypatch.setenv("FLIGHTSCOUT_NO_CACHE", "1")
    monkeypatch.setattr(cache, "put", lambda *a, **k: None)
    q = SearchQuery(origins=["SAN"], destinations=["OSL"], departure=date(2026, 11, 10),
                    return_date=date(2026, 11, 20), currency="USD", sources=["google"])
    its = google.search(q)
    best = min(its, key=lambda i: i.price)
    assert best.price == 727.0 and best.return_pending
    assert best.slices[0].segments[0].carrier == "DL"


def test_no_fill_without_unpriced_rows(monkeypatch):
    called = []
    monkeypatch.setattr(google, "_browser_prices", lambda f, c: called.append(1) or {})
    others = [parse_flight_row(r) for r in ROWS]

    def fake_search(self, filters, top_n, currency):
        self.outbounds, self.filters = others, filters
        return []

    monkeypatch.setattr(google._DiverseSearch, "search", fake_search)
    monkeypatch.setenv("FLIGHTSCOUT_NO_CACHE", "1")
    monkeypatch.setattr(cache, "put", lambda *a, **k: None)
    q = SearchQuery(origins=["SAN"], destinations=["OSL"], departure=date(2026, 11, 10),
                    return_date=date(2026, 11, 20), currency="USD", sources=["google"])
    assert len(google.search(q)) == 3
    assert not called
