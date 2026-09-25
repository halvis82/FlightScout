"""Google Flights via the ``fli`` library (reads the data embedded in the
results page, so it survives Google's August 2026 API lockdown)."""

from __future__ import annotations

import logging
from datetime import date, timedelta

from fli.core.links import google_flights_url
from fli.core.parsers import resolve_airport
from fli.models import (
    DateSearchFilters,
    FlightSearchFilters,
    FlightSegment,
    MaxStops,
    PassengerInfo,
    SeatType,
    SortBy,
    TripType,
)
from fli.search import SearchDates, SearchFlights
from fli.search import flights as _fli_flights

# Google's results page only embeds the ~10 "top" departing flights unless
# asked for all of them. This tfu flag (same as fast-flights uses) makes it
# embed the full list, so we see every airline, like Google's Cheapest tab.
_ALL_RESULTS = "&tfu=EgQIABABIgA"
_orig_page_url = _fli_flights.page_url
_fli_flights.page_url = lambda *a, **k: _orig_page_url(*a, **k) + _ALL_RESULTS

from .. import cache
from ..models import DatePrice, Itinerary, SearchQuery, Segment, Slice

log = logging.getLogger(__name__)

_SEAT = {
    "economy": SeatType.ECONOMY,
    "premium": SeatType.PREMIUM_ECONOMY,
    "business": SeatType.BUSINESS,
    "first": SeatType.FIRST,
}
_STOPS = {None: MaxStops.ANY, 0: MaxStops.NON_STOP, 1: MaxStops.ONE_STOP_OR_FEWER, 2: MaxStops.TWO_OR_FEWER_STOPS}


def _diverse(flights: list, n: int) -> list:
    """Put the cheapest outbound of each airline first so round trip
    expansion covers many carriers, not just the cheapest one."""
    def key(f):
        return f.price if f.price is not None else float("inf")
    ordered = sorted(flights, key=key)
    first, rest, seen = [], [], set()
    for f in ordered:
        carrier = tuple(sorted({leg.airline.name for leg in f.legs}))
        (rest if carrier in seen else first).append(f)
        seen.add(carrier)
    return (first + rest)[: max(n, 1)] + (first + rest)[max(n, 1):]


class _DiverseSearch(SearchFlights):
    """Expands the cheapest outbound per airline first, and remembers every
    outbound option so the unexpanded ones can still be listed."""

    outbounds: list = []
    filters = None
    wide = True  # slice the outbound search to cover Google's Cheapest tab

    def _fetch_flights(self, filters, *, capture_session, **kw):
        """For the outbound list, also fetch a few slices of the search (1 stop
        or fewer, each alliance) and merge them. Google's page only embeds
        ~50 flights ranked by "Best", so the long, odd, cheap connections from
        its Cheapest tab are often missing; the slices surface them (tested:
        84 itineraries covering 42 of 43 Cheapest tab departures, vs 49)."""
        if (not self.wide or not capture_session or filters.stops != MaxStops.ANY or filters.alliances
                or filters.airlines or filters.alliances_exclude):
            return super()._fetch_flights(filters, capture_session=capture_session, **kw)
        from copy import deepcopy

        from fli.models import Alliance

        variants = [filters]
        # slices: nonstop, 1 stop or fewer, each alliance, and airlines in no
        # alliance (Philippine, WestJet, Emirates...: often the cheap long
        # connections Google's Cheapest tab shows)
        for extra in ({"stops": MaxStops.NON_STOP}, {"stops": MaxStops.ONE_STOP_OR_FEWER},
                      *({"alliances": [a]} for a in Alliance), {"alliances_exclude": list(Alliance)}):
            f = deepcopy(filters)
            for k, v in extra.items():
                setattr(f, k, v)
            variants.append(f)

        def one(f, first=False):
            try:
                return super(_DiverseSearch, self)._fetch_flights(f, capture_session=first, **kw) or []
            except Exception:
                if first:
                    raise
                return []

        results = _fli_flights.parallel_map(lambda i: one(variants[i], i == 0), list(range(len(variants))))
        merged, seen = [], set()
        for rows in results:
            for fl in rows:
                key = tuple((leg.airline.name, leg.flight_number, leg.departure_datetime) for leg in fl.legs)
                if key not in seen:
                    seen.add(key)
                    merged.append(fl)
        return merged

    def _expand_multi_leg(self, flights, filters, *, top_n, **kw):
        ordered = _diverse(list(flights), top_n)
        if not self.outbounds:  # first level only (the outbound list)
            self.outbounds, self.filters = ordered, filters
            # Google sometimes lists outbounds without a price (depends on the
            # asking IP; seen for the cheapest Delta/SAS options SAN-OSL). They
            # sort last, so they were never expanded and silently dropped even
            # though they were the cheapest on Google's page. Always expand a
            # few: the return page prices them.
            head, seen = ordered[:top_n], set()
            priceless = []
            for f in ordered[top_n:]:
                k = tuple((leg.airline.name, leg.flight_number) for leg in f.legs)
                if f.price is None and k not in seen:
                    seen.add(k)
                    priceless.append(f)
            extra = priceless[:6]
            if extra:
                rest = [f for f in ordered[top_n:] if not any(f is e for e in extra)]
                ordered, top_n = head + extra + rest, top_n + len(extra)
        return super()._expand_multi_leg(ordered, filters, top_n=top_n, **kw)


def _legs_key(f) -> tuple:
    return tuple((leg.airline.name, leg.flight_number, leg.departure_datetime) for leg in f.legs)


_SOCS = {"name": "SOCS", "value": "CAESEwgDEgk0ODE3Nzk3MjQaAmVuIAEaBgiA_LyaBg", "domain": ".google.com", "path": "/"}


def _browser_prices(filters, currency: str) -> dict[tuple, float]:
    """Prices for the outbound rows Google embedded without one (it depends
    on the asking IP). The page's JavaScript fetches them (GetShoppingResults,
    which only a real browser can sign), so load the page in the shared
    Chrome and read that response. In extension mode the server's own page
    load fills them instead. Empty when neither works."""
    from . import _browser
    from .. import browser_fetch

    from fli.search._decoders import parse_flight_row
    from fli.search._tfs import build_tfs
    from fli.search._wire import iter_wrb_chunks

    url = _fli_flights.page_url(build_tfs(filters), currency)
    if browser_fetch.active():
        # Extension mode runs on the server: the visitor's IP got the rows
        # unpriced, but the server's usually gets them priced. One page load.
        try:
            from fli.search.client import get_client

            inner = browser_fetch._orig["flights"](get_client(), url)
            rows = [r for i in (2, 3) if isinstance(inner[i], list) for r in inner[i][0]]
        except Exception as e:
            log.info("google: server prices unavailable: %s", e)
            return {}
        return _priced(rows, parse_flight_row)
    if not _browser.available():
        return {}

    def job(page) -> str:
        # A fresh context each time: in the long lived shared profile Google
        # answered with a different (pricier, $840 vs $727 SAN-OSL) fare set.
        ctx = page.context.browser.new_context(locale="en-US")
        try:
            ctx.add_cookies([_SOCS])
            pg = ctx.new_page()
            got = _browser.capture(pg, lambda: pg.goto(url, wait_until="commit", timeout=30000),
                                   lambda u: "GetShoppingResults" in u, timeout=20)
            return got[-1][1] if got else ""
        finally:
            ctx.close()

    try:
        # streamed: the first chunk is the airports, flight rows come later
        rows = [r for inner in iter_wrb_chunks(_browser.run(job, "google", timeout=60))
                if isinstance(inner, list) and len(inner) > 3
                for i in (2, 3) if isinstance(inner[i], list) and inner[i] and isinstance(inner[i][0], list)
                for r in inner[i][0]]
    except Exception as e:
        log.info("google: browser prices unavailable: %s", e)
        return {}
    return _priced(rows, parse_flight_row)


def _priced(rows: list, parse) -> dict[tuple, float]:
    out: dict[tuple, float] = {}
    for row in rows:
        try:
            f = parse(row)
        except Exception:
            continue
        if f.price is not None:
            out[_legs_key(f)] = float(f.price)
    return out


def _return_page_url(filters, outbound, currency: str) -> str:
    """Google's "choose your return" page for a selected outbound."""
    from copy import deepcopy

    from fli.search._tfs import build_tfs

    f = deepcopy(filters)
    f.flight_segments[0].selected_flight = outbound
    return _fli_flights.page_url(build_tfs(f), currency)


def _airports(codes: list[str]):
    out = []
    for c in codes:
        try:
            out.append([resolve_airport(c), 0])
        except Exception:
            log.debug("google: unknown airport %s", c)
    if not out:
        raise ValueError(f"no airports Google knows in {codes}")
    return out


def _slice(res) -> Slice:
    segs = [
        Segment(
            origin=leg.departure_airport.name.lstrip("_"),
            destination=leg.arrival_airport.name.lstrip("_"),
            departure=leg.departure_datetime,
            arrival=leg.arrival_datetime,
            carrier=leg.airline.name.lstrip("_"),
            carrier_name=leg.airline.value,
            flight_number=leg.flight_number,
            duration_min=leg.duration,
            aircraft=leg.aircraft,
        )
        for leg in res.legs
    ]
    return Slice(segments=segs, duration_min=res.duration)


def search(q: SearchQuery, top_n: int = 8, wide: bool = True) -> list[Itinerary]:
    """``wide`` adds the sliced outbound searches that cover Google's Cheapest
    tab (8 page loads instead of 1). The planner, multi city and tracker call
    this many times per run and pass wide=False."""
    key = f"google:{q.model_dump_json()}:{top_n}:{wide}"
    if (hit := cache.get(key)) is not None:
        return [Itinerary(**x) for x in hit]

    segments = [
        FlightSegment(
            departure_airport=_airports(q.origins),
            arrival_airport=_airports(q.destinations),
            travel_date=q.departure.isoformat(),
        )
    ]
    if q.return_date:
        segments.append(
            FlightSegment(
                departure_airport=_airports(q.destinations),
                arrival_airport=_airports(q.origins),
                travel_date=q.return_date.isoformat(),
            )
        )
    filters = FlightSearchFilters(
        trip_type=TripType.ROUND_TRIP if q.return_date else TripType.ONE_WAY,
        passenger_info=PassengerInfo(adults=q.adults),
        flight_segments=segments,
        stops=_STOPS.get(q.max_stops, MaxStops.ANY),
        seat_type=_SEAT[q.cabin],
        sort_by=SortBy.CHEAPEST,
    )
    client = _DiverseSearch()
    client.outbounds = []
    client.wide = wide
    try:
        results = client.search(filters, top_n=top_n, currency=q.currency) or []
    except Exception as e:
        msg = str(e)
        if "429" in msg or "unusual traffic" in msg.lower() or "captcha" in msg.lower():
            raise RuntimeError("rate_limited: Google is throttling this server. Try the local runner "
                               "(`flightscout serve`) or again later.") from e
        raise
    # Rows Google listed without a price (see _expand_multi_leg) get it from
    # the page's own JavaScript in a real Chrome, where one is installed.
    obs = client.outbounds or [r for r in results if not isinstance(r, tuple)]
    fill = _browser_prices(filters, q.currency) if any(o.price is None for o in obs) else {}
    out: list[Itinerary] = []
    for r in results:
        parts = list(r) if isinstance(r, tuple) else [r]
        price = parts[0].price
        if price is None and not isinstance(r, tuple):
            price = fill.get(_legs_key(r))
        if price is None:
            continue
        url = client.build_flight_booking_url(
            r, currency=q.currency, seat_type=_SEAT[q.cabin], passenger_info=filters.passenger_info
        )
        carriers = {leg.airline.value for p in parts for leg in p.legs}
        out.append(
            Itinerary(
                source="google",
                price=float(price),
                currency=parts[0].currency or q.currency,
                slices=[_slice(p) for p in parts],
                booking_url=url,
                seller="Google Flights",
                seller_kind="metasearch",
                warnings=[] if len(carriers) == 1 else [],
            )
        )
    # Every other outbound option with its round trip price (Google's list),
    # return to be picked on Google.
    if q.return_date and client.outbounds:
        expanded = {_legs_key(r[0] if isinstance(r, tuple) else r) for r in results
                    if (r[0] if isinstance(r, tuple) else r).price is not None}
        listed = set()
        for ob in client.outbounds:
            k = _legs_key(ob)
            price = ob.price if ob.price is not None else fill.get(k)
            if k in expanded or k in listed or price is None:
                continue
            listed.add(k)
            try:
                url = _return_page_url(client.filters, ob, q.currency)
            except Exception:
                url = search_url(q)
            out.append(Itinerary(
                source="google", price=float(price), currency=ob.currency or q.currency, slices=[_slice(ob)],
                booking_url=url, seller="Google Flights", seller_kind="metasearch", return_pending=True,
            ))
    cache.put(key, [i.model_dump(mode="json") for i in out])
    return out


def search_url(q: SearchQuery) -> str:
    return google_flights_url(
        q.origins[0], q.destinations[0], q.departure.isoformat(),
        q.return_date.isoformat() if q.return_date else None, currency=q.currency,
    )


def dates(origin: str, destination: str, start: date, end: date, currency: str = "USD",
          trip_days: int | None = None, cabin: str = "economy") -> list[DatePrice]:
    """Cheapest price per departure date in [start, end]. Costs one request per
    date on Google now, so keep ranges modest (the engine caps at 60 days)."""
    end = min(end, start + timedelta(days=60))
    key = f"gdates:{origin}:{destination}:{start}:{end}:{currency}:{trip_days}:{cabin}"
    if (hit := cache.get(key, ttl=6 * 3600)) is not None:
        return [DatePrice(**x) for x in hit]
    seg = [FlightSegment(departure_airport=_airports([origin]), arrival_airport=_airports([destination]),
                         travel_date=start.isoformat())]
    if trip_days:
        seg.append(FlightSegment(departure_airport=_airports([destination]), arrival_airport=_airports([origin]),
                                 travel_date=(start + timedelta(days=trip_days)).isoformat()))
    filters = DateSearchFilters(
        trip_type=TripType.ROUND_TRIP if trip_days else TripType.ONE_WAY,
        passenger_info=PassengerInfo(adults=1),
        flight_segments=seg,
        seat_type=_SEAT[cabin],
        from_date=start.isoformat(),
        to_date=end.isoformat(),
        duration=trip_days,
    )
    res = SearchDates().search(filters, currency=currency) or []
    out = []
    for d in res:
        dep = d.date[0].date()
        ret = d.date[1].date() if len(d.date) > 1 else None
        out.append(DatePrice(
            origin=origin, destination=destination, departure=dep, return_date=ret,
            price=d.price, currency=d.currency or currency, source="google",
            booking_url=google_flights_url(origin, destination, dep.isoformat(),
                                           ret.isoformat() if ret else None, currency=currency),
        ))
    cache.put(key, [x.model_dump(mode="json") for x in out])
    return out
