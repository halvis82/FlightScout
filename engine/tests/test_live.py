"""Hit the real sources. Run with FLIGHTSCOUT_LIVE=1 pytest -m live."""

from datetime import date, timedelta

import pytest

from flightscout.explore import explore
from flightscout.models import SearchQuery
from flightscout.search import search

pytestmark = pytest.mark.live
D = date.today() + timedelta(days=45)


def test_google_and_kiwi_return_priced_results():
    r = search(SearchQuery(origins=["OSL"], destinations=["CPH"], departure=D, sources=["google", "kiwiweb"]))
    srcs = {t.tickets[0].source for t in r.trips}
    assert {"google", "kiwiweb"} <= srcs, r.errors
    assert all(t.total_price > 0 and t.tickets[0].booking_url.startswith("http") for t in r.trips)


def test_fast_explore_is_broad():
    dests, errors = explore("SAN", D, D + timedelta(days=7), "USD", (3, 7), sources=["kiwiweb", "kayak"], regions=["anywhere"])
    assert len(dests) >= 30, errors


def test_direct_airline_source_wideroe():
    r = search(SearchQuery(origins=["BGO"], destinations=["TRD"], departure=D, sources=["wideroe"]))
    assert r.trips, r.errors
