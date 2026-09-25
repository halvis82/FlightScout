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
        return super()._expand_multi_leg(ordered, filters, top_n=top_n, **kw)


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
    out: list[Itinerary] = []
    for r in results:
        parts = list(r) if isinstance(r, tuple) else [r]
        price = parts[0].price
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
        expanded = {tuple((l.airline.name, l.flight_number) for l in (r[0] if isinstance(r, tuple) else r).legs)
                    for r in results}
        for ob in client.outbounds:
            k = tuple((l.airline.name, l.flight_number) for l in ob.legs)
            if k in expanded or ob.price is None:
                continue
            try:
                url = _return_page_url(client.filters, ob, q.currency)
            except Exception:
                url = search_url(q)
            out.append(Itinerary(
                source="google", price=float(ob.price), currency=ob.currency or q.currency, slices=[_slice(ob)],
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
