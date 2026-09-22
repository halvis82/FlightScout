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


def search(q: SearchQuery, top_n: int = 3) -> list[Itinerary]:
    key = f"google:{q.model_dump_json()}:{top_n}"
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
    client = SearchFlights()
    results = client.search(filters, top_n=top_n, currency=q.currency) or []
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
