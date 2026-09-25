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
    if "403" in r.errors.get("wideroe", ""):
        pytest.skip("Widerøe's Cloudflare blocks this IP (GitHub runners); works from home and Vercel")
    assert r.trips, r.errors


def test_google_covers_the_cheapest_tab():
    """Open Google Flights in a real browser, click Cheapest, expand every
    flight, and check FlightScout's Google results contain nearly all of them
    (by departure time). Guards against Google changing what its page embeds."""
    pytest.importorskip("playwright")
    import re

    from fli.core.parsers import resolve_airport
    from fli.models import FlightSearchFilters, FlightSegment, PassengerInfo, TripType
    from fli.search._tfs import build_tfs, page_url
    from playwright.sync_api import sync_playwright

    from flightscout.sources import google

    dep, ret = D, D + timedelta(days=11)
    ours = google.search(SearchQuery(origins=["LAX"], destinations=["NRT"], departure=dep, return_date=ret))
    times = {i.slices[0].departure.strftime("%-I:%M %p") for i in ours}
    a = lambda c: [[resolve_airport(c), 0]]  # noqa: E731
    f = FlightSearchFilters(trip_type=TripType.ROUND_TRIP, passenger_info=PassengerInfo(adults=1), flight_segments=[
        FlightSegment(departure_airport=a("LAX"), arrival_airport=a("NRT"), travel_date=dep.isoformat()),
        FlightSegment(departure_airport=a("NRT"), arrival_airport=a("LAX"), travel_date=ret.isoformat())])
    with sync_playwright() as p:
        try:
            b = p.chromium.launch(channel="chrome", headless=True)
        except Exception:
            b = p.chromium.launch(headless=True)
        ctx = b.new_context(locale="en-US")
        ctx.add_cookies([{"name": "SOCS", "value": "CAESEwgDEgk0ODE3Nzk3MjQaAmVuIAEaBgiA_LyaBg",
                          "domain": ".google.com", "path": "/"}])
        pg = ctx.new_page()
        pg.goto(page_url(build_tfs(f), "USD"), wait_until="networkidle")
        pg.get_by_role("tab", name=re.compile("Cheapest")).first.click()
        pg.wait_for_timeout(3000)
        for _ in range(5):
            more = pg.get_by_role("button", name=re.compile("more flights", re.I))
            if more.count():
                more.first.click()
                pg.wait_for_timeout(2500)
        items = [t for t in pg.locator("li").all_inner_texts() if re.search(r"\d:\d\d", t) and "$" in t]
        b.close()
    theirs = {re.search(r"(\d{1,2}:\d{2}\s?[AP]M)", t).group(1).replace("\u202f", " ") for t in items}
    assert theirs, "could not read Google's Cheapest tab"
    coverage = len(theirs & times) / len(theirs)
    assert coverage >= 0.9, f"only {coverage:.0%} of Google's Cheapest tab: missing {sorted(theirs - times)[:10]}"
