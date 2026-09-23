"""Multi source search: fan out to every enabled source in parallel, normalize
currency, merge duplicates and wrap each ticket as a Trip."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from . import airports, fx, sellers
from .models import Itinerary, SearchQuery, SearchResult, Trip
from .models import DatePrice
from .sources import (condor, flair, google, kiwi, kiwiweb, norse, serpapi, skyairline, skyscanner, vivaaerobus,
                      volaris, volotea, wideroe, wizzair)

log = logging.getLogger(__name__)

SOURCES = {
    "google": lambda q: _google(q), "kiwi": kiwi.search, "serpapi": serpapi.search, "volaris": volaris.search,
    "wideroe": wideroe.search, "skyairline": skyairline.search, "norse": norse.search,
    "volotea": volotea.search, "condor": condor.search, "flair": flair.search, "kiwiweb": kiwiweb.search,
}

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
        for res in ex.map(lambda dr: google.search(q.model_copy(update={"departure": dr[0], "return_date": dr[1]})), best):
            out.extend(res)
    return out


def _google(q: SearchQuery) -> list[Itinerary]:
    if q.departure_flex_days or q.return_flex_days:
        return _google_flex(q)
    return google.search(q)


def search(q: SearchQuery, seller_rules: dict[str, str] | None = None) -> SearchResult:
    q = q.model_copy(update={
        "origins": airports.expand_nearby(q.origins, q.nearby_km),
        "destinations": airports.expand_nearby(q.destinations, q.nearby_km),
    })
    srcs = [s for s in q.sources if s in SOURCES and (s != "serpapi" or serpapi.enabled())]
    errors: dict[str, str] = {}
    found: list[Itinerary] = []
    with ThreadPoolExecutor(max_workers=len(srcs) or 1) as ex:
        futs = {s: ex.submit(SOURCES[s], q) for s in srcs}
        for s, f in futs.items():
            try:
                found.extend(f.result())
            except Exception as e:  # one source failing must not sink the search
                log.warning("source %s failed: %s", s, e)
                errors[s] = str(e)[:300]
    items = merge([sellers.annotate(to_currency(i, q.currency)) for i in found])
    trips = [Trip(tickets=[i], total_price=i.price, currency=i.currency, kind="single",
                  risks=list(i.warnings)) for i in items]
    trips = sellers.apply_rules(trips, seller_rules)
    return SearchResult(query=q, trips=trips, errors=errors, google_url=google.search_url(q))
