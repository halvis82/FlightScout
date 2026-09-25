"""Multi source search: fan out to every enabled source in parallel, normalize
currency, merge duplicates and wrap each ticket as a Trip."""

from __future__ import annotations

import contextvars
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

from . import airports, fx, sellers
from .models import Itinerary, SearchQuery, SearchResult, Trip
from .models import DatePrice
from .sources import (_browser, condor, flair, google, kiwi, kiwiweb, norse, serpapi, skyairline, skyscanner,
                      vivaaerobus, volaris, volotea, wideroe, wizzair)
from .sources import (allegiant_browser, norwegian_browser, southwest_browser, transavia_browser,
                      vivaaerobus_browser)
from .sources import aerolineas, aeromexico, alaska, arajet, breeze, frontier, jetblue
from .sources import (avelo_browser, caribbean_browser, caymanairways_browser, porter_browser, united_browser,
                      westjet_browser, wingo_browser)
from .sources import (almosafer, aviasales_browser, booking, cleartrip, edreams, expedia, gotogate, kayakweb,
                      mytrip, opodo, priceline, traveloka, tripcom_browser, wego)

log = logging.getLogger(__name__)

SOURCES = {
    "google": lambda q: _google(q), "kiwi": kiwi.search, "serpapi": serpapi.search, "volaris": volaris.search,
    "wideroe": wideroe.search, "skyairline": skyairline.search, "norse": norse.search,
    "volotea": volotea.search, "condor": condor.search, "flair": flair.search, "kiwiweb": kiwiweb.search,
}

# Airlines that block plain HTTP clients, read through one shared real Chrome
# (sources/_browser.py). Not in the default source list (Vercel has no
# browser): search() adds them by itself wherever Chrome and Playwright are
# installed (local runner, CLI, GitHub tracker) and the query asks for direct
# airline sources. Each one also gates itself on its own network. Set
# FLIGHTSCOUT_BROWSER=0 to turn them off.
BROWSER_SOURCES = {
    "transavia": transavia_browser.search, "norwegian": norwegian_browser.search,
    "southwest": southwest_browser.search, "vivaaerobus": vivaaerobus_browser.search,
    "allegiant": allegiant_browser.search,
    "avelo": avelo_browser.search, "united": united_browser.search, "porter": porter_browser.search,
    "westjet": westjet_browser.search, "caribbean": caribbean_browser.search,
    "caymanairways": caymanairways_browser.search, "wingo": wingo_browser.search,
}
SOURCES.update(BROWSER_SOURCES)
SOURCES.update({
    "frontier": frontier.search, "breeze": breeze.search, "jetblue": jetblue.search, "alaska": alaska.search,
    "arajet": arajet.search, "aeromexico": aeromexico.search, "aerolineas": aerolineas.search,
})
# Booking sites (OTAs and metasearch), each verified against its own results
# page. The "otas" group: plain HTTP ones everywhere, the headless Chrome ones
# only where Chrome is installed.
OTAS = {
    "booking": booking.search, "kayakweb": kayakweb.search, "momondo": kayakweb.search_momondo,
    "cheapflights": kayakweb.search_cheapflights, "expedia": expedia.search, "orbitz": expedia.search_orbitz,
    "travelocity": expedia.search_travelocity, "priceline": priceline.search, "wego": wego.search,
    "gotogate": gotogate.search, "mytrip": mytrip.search,
}
OTAS_BROWSER = {
    "tripcom": tripcom_browser.search, "aviasales": aviasales_browser.search, "edreams": edreams.search,
    "opodo": opodo.search, "almosafer": almosafer.search, "traveloka": traveloka.search, "cleartrip": cleartrip.search,
}
SOURCES.update(OTAS)
SOURCES.update(OTAS_BROWSER)
OTA_WAIT = float(os.environ.get("FLIGHTSCOUT_OTA_WAIT", "45"))
# Direct airline sources over plain HTTP. Each gates itself on its network.
AIRLINES = ["volaris", "wideroe", "skyairline", "norse", "volotea", "condor", "flair",
            "frontier", "breeze", "jetblue", "alaska", "arajet", "aeromexico", "aerolineas"]
_DIRECT = set(AIRLINES)


def expand_sources(names: list[str]) -> list[str]:
    """Resolve the "airlines" group (and legacy explicit airline lists) to
    every direct airline source, plus the browser ones where Chrome is here."""
    out = [s for s in names if s in SOURCES and (s != "serpapi" or serpapi.enabled())]
    if "airlines" in names:
        out += [s for s in AIRLINES if s not in out]
    if ("airlines" in names or set(names) & _DIRECT) and _browser.available():
        out += [s for s in BROWSER_SOURCES if s not in out]
    if "otas" in names:
        out += [s for s in OTAS if s not in out]
        if _browser.available():
            out += [s for s in OTAS_BROWSER if s not in out]
    return out

# Airline low fare calendars (one way, cheapest fare per day). Each module
# gates itself with relevant(), so only carriers that fly the market are asked.
CALENDARS = {
    "volaris": volaris, "vivaaerobus": vivaaerobus, "wizzair": wizzair, "volotea": volotea,
    "skyairline": skyairline, "flair": flair, "norse": norse,
    # Every route: Kiwi's own per day calendar and Skyscanner's cached month grid.
    "kiwiweb": kiwiweb, "skyscanner": skyscanner,
}


def direct_dates(origin: str, dest: str, start, end, currency: str) -> tuple[list[DatePrice], dict[str, str]]:
    """Every relevant airline calendar for a route, plus per source errors."""
    mods = {n: m for n, m in CALENDARS.items() if m.relevant([origin], [dest])}
    out: list[DatePrice] = []
    errors: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=len(mods) or 1) as ex:
        futs = {n: ex.submit(m.dates, origin, dest, start, end, currency) for n, m in mods.items()}
        for n, f in futs.items():
            try:
                out.extend(f.result())
            except Exception as e:
                log.warning("calendar %s failed: %s", n, e)
                errors[n] = str(e)[:300]
    return out, errors


def cheapest_per_day(rows: list[DatePrice]) -> list[DatePrice]:
    best: dict = {}
    for r in rows:
        k = (r.departure, r.return_date)
        if k not in best or r.price < best[k].price:
            best[k] = r
    return sorted(best.values(), key=lambda r: r.departure)


def to_currency(it: Itinerary, cur: str) -> Itinerary:
    if it.currency.upper() != cur.upper():
        it.price = round(fx.convert(it.price, it.currency, cur), 2)
        it.currency = cur.upper()
    return it


def merge(items: list[Itinerary]) -> list[Itinerary]:
    """Same flights from the same kind of seller collapse into the cheapest.
    The same flights sold by an OTA and via Google both stay, since they are
    genuinely different purchases."""
    best: dict[tuple[str, str], Itinerary] = {}
    for it in items:
        k = (it.flight_key, it.seller_kind)
        if k not in best or it.price < best[k].price:
            best[k] = it
    return sorted(best.values(), key=lambda i: i.price)


def _google_flex(q: SearchQuery) -> list[Itinerary]:
    """Flexible dates on Google: price every date in the window from the
    calendar, then run full searches on the 3 cheapest date combinations."""
    from datetime import date as _date, timedelta

    df, rf = q.departure_flex_days, q.return_flex_days
    tomorrow = _date.today() + timedelta(days=1)
    lo, hi = max(tomorrow, q.departure - timedelta(days=df)), q.departure + timedelta(days=df)
    o, d = q.origins[0], q.destinations[0]
    pairs: list[tuple[float, _date, _date | None]] = []
    if q.return_date:
        base = (q.return_date - q.departure).days
        rlo, rhi = q.return_date - timedelta(days=rf), q.return_date + timedelta(days=rf)
        lengths = sorted({max(1, base + k) for k in range(-(df + rf), df + rf + 1)})
        # keep it bounded: at most 5 trip lengths around the requested one
        lengths = sorted(lengths, key=lambda n: abs(n - base))[:5]
        for n in lengths:
            for dp in google.dates(o, d, lo, hi, q.currency, trip_days=n, cabin=q.cabin):
                r = dp.departure + timedelta(days=n)
                if rlo <= r <= rhi:
                    pairs.append((dp.price, dp.departure, r))
    else:
        pairs = [(dp.price, dp.departure, None) for dp in google.dates(o, d, lo, hi, q.currency, cabin=q.cabin)]
    pairs.sort()
    best = list(dict.fromkeys((p[1], p[2]) for p in pairs))[:3]
    if (q.departure, q.return_date) not in best:
        best.append((q.departure, q.return_date))
    out: list[Itinerary] = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        # the exact dates get the wide (Cheapest tab) search, alternatives a single page
        runs = [ex.submit(contextvars.copy_context().run, google.search,
                          q.model_copy(update={"departure": dr[0], "return_date": dr[1]}), 8,
                          dr == (q.departure, q.return_date)) for dr in best]
        for res in (f.result() for f in runs):
            out.extend(res)
    return out


def _google(q: SearchQuery) -> list[Itinerary]:
    try:
        if q.departure_flex_days or q.return_flex_days:
            return _google_flex(q)
        return google.search(q)
    except Exception as e:
        # Google refusing our IP: fall back to a paid Google Flights API when
        # one is configured (SEARCHAPI_KEY, then SERPAPI_KEY). Free otherwise.
        if "rate_limited" not in str(e) and "429" not in str(e):
            raise
        from .sources import searchapi

        for fallback in (searchapi, serpapi):
            if fallback.enabled():
                log.warning("google blocked, using %s", fallback.__name__.rsplit(".", 1)[-1])
                return fallback.search(q)
        raise


def search(q: SearchQuery, seller_rules: dict[str, str] | None = None) -> SearchResult:
    q = q.model_copy(update={
        "origins": airports.expand_nearby(q.origins, q.nearby_km),
        "destinations": airports.expand_nearby(q.destinations, q.nearby_km),
    })
    srcs = expand_sources(list(q.sources))
    errors: dict[str, str] = {}
    found: list[Itinerary] = []
    ex = ThreadPoolExecutor(max_workers=len(srcs) or 1)
    # copy_context: browser mode (see browser_fetch.py) must reach the source threads
    futs = {s: ex.submit(contextvars.copy_context().run, SOURCES[s], q) for s in srcs}
    # Booking sites and browser read airlines can be slow (up to a minute or
    # two): don't hold the search
    # for them. Late ones keep running and fill the cache for the next search.
    deadline = time.monotonic() + OTA_WAIT
    for s, f in futs.items():
        try:
            if s in OTAS or s in OTAS_BROWSER or s in BROWSER_SOURCES:
                found.extend(f.result(timeout=max(0.0, deadline - time.monotonic())))
            else:
                found.extend(f.result())
        except FutureTimeout:
            errors[s] = f"still searching after {OTA_WAIT:.0f} s (cached for the next search)"
        except Exception as e:  # one source failing must not sink the search
            log.warning("source %s failed: %s", s, e)
            errors[s] = str(e)[:300]
    ex.shutdown(wait=False)
    items = merge([sellers.annotate(to_currency(i, q.currency)) for i in found])
    trips = [Trip(tickets=[i], total_price=i.price, currency=i.currency, kind="single",
                  risks=list(i.warnings)) for i in items]
    trips = sellers.apply_rules(trips, seller_rules)
    return SearchResult(query=q, trips=trips, errors=errors, google_url=google.search_url(q))
