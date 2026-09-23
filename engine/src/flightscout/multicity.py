"""Multi city trips in a fixed order where each leg has its own date window:
"SAN to JFK around Mar 3 (±2 days), JFK to OSL any time after, OSL to CDG,
be in Paris by Mar 20, CDG to SAN". Each leg is priced as its own ticket from
Kiwi (one date range request per leg, includes connections through other
cities) and Google (full searches on the cheapest dates of the window), then a
beam search picks sequences that respect the order and leave enough time
between legs."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

from pydantic import BaseModel, Field

from . import airports, sellers
from .models import Itinerary, SearchQuery, Stopover, Trip
from .planner import PlanResult
from .search import merge, to_currency
from .sources import google, kiwi


class Leg(BaseModel):
    origins: list[str]
    destinations: list[str]
    date: date
    before: int = 0  # may depart this many days earlier
    after: int = 0  # may depart this many days later
    arrive_by: date | None = None  # must land on or before this date


class MultiRequest(BaseModel):
    legs: list[Leg]
    currency: str = "USD"
    cabin: str = "economy"
    adults: int = 1
    min_gap_hours: float = 4.0  # between landing and the next leg's departure
    beam: int = 8
    max_results: int = 20
    seller_rules: dict[str, str] | None = None
    value_of_time_per_hour: float = 15.0


def _window(leg: Leg) -> tuple[date, date]:
    lo = leg.date - timedelta(days=leg.before)
    hi = leg.date + timedelta(days=leg.after)
    if leg.arrive_by:
        hi = min(hi, leg.arrive_by)
    lo = max(lo, date.today() + timedelta(days=1))
    return lo, max(lo, hi)


def _leg_options(leg: Leg, req: MultiRequest, errors: dict[str, str]) -> list[Itinerary]:
    o = airports.expand(leg.origins)
    d = airports.expand(leg.destinations)
    lo, hi = _window(leg)
    found: list[Itinerary] = []

    def kiwi_range():
        return kiwi.search_range(o[0], d[0], lo, hi, req.currency, None, req.cabin)

    def google_best():
        days = [lo + timedelta(days=i) for i in range((hi - lo).days + 1)]
        if len(days) > 1:
            try:
                cal = google.dates(o[0], d[0], lo, hi, req.currency, cabin=req.cabin)
                days = [x.departure for x in sorted(cal, key=lambda x: x.price)[:2]] or days[:1]
            except Exception:
                days = [leg.date if lo <= leg.date <= hi else lo]
        out = []
        for day in days[:2]:
            out += google.search(SearchQuery(origins=o, destinations=d, departure=day, currency=req.currency,
                                             cabin=req.cabin, adults=req.adults), top_n=1)
        return out

    with ThreadPoolExecutor(max_workers=2) as ex:
        jobs = {"kiwi": ex.submit(kiwi_range), "google": ex.submit(google_best)}
        for name, f in jobs.items():
            try:
                found += f.result()
            except Exception as e:
                errors[f"{name} {o[0]}-{d[0]}"] = str(e)[:200]
    items = merge([sellers.annotate(to_currency(i, req.currency)) for i in found])
    if leg.arrive_by:
        items = [i for i in items if i.slices[-1].arrival.date() <= leg.arrive_by]
    return items


def plan_multicity(req: MultiRequest) -> PlanResult:
    errors: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        options = list(ex.map(lambda lg: _leg_options(lg, req, errors), req.legs))
    requests = sum(3 for _ in req.legs)

    # beam: (tickets, last arrival, cost)
    beam: list[tuple[list[Itinerary], datetime | None, float]] = [([], None, 0.0)]
    gap = timedelta(hours=req.min_gap_hours)
    for opts in options:
        nxt = []
        for tickets, arr, cost in beam:
            for it in sorted(opts, key=lambda i: i.price)[:25]:
                if arr and it.slices[0].departure < arr + gap:
                    continue
                nxt.append((tickets + [it], it.slices[-1].arrival, cost + it.price))
        # keep variety: best by cost, plus best by total travel time
        by_cost = sorted(nxt, key=lambda b: b[2])[: req.beam]
        by_time = sorted(nxt, key=lambda b: sum(t.duration_min for t in b[0]))[: req.beam // 2]
        beam = list({tuple(t.id for t in b[0]): b for b in by_cost + by_time}.values())
        if not beam:
            break

    trips: list[Trip] = []
    for tickets, _, cost in beam:
        if len(tickets) != len(req.legs):
            continue
        stops = [Stopover(airport=a.slices[-1].destination,
                          hours=round((b.slices[0].departure - a.slices[-1].arrival).total_seconds() / 3600, 1))
                 for a, b in zip(tickets, tickets[1:])]
        risks = ["Each leg is a separate ticket. A change or delay on one doesn't carry over to the others."]
        for tk in tickets:
            risks.extend(tk.warnings)
        t = Trip(tickets=tickets, total_price=round(cost, 2), currency=req.currency, kind="multicity",
                 stopovers=stops, risks=list(dict.fromkeys(risks)))
        t.score = round(cost + req.value_of_time_per_hour * sum(tk.duration_min for tk in tickets) / 60, 2)
        trips.append(t)
    trips = sellers.apply_rules(trips, req.seller_rules)
    trips.sort(key=lambda t: t.score or 0)
    # collapse near duplicates (same route and price, different later dates)
    seen: set = set()
    uniq = []
    for t in trips:
        sig = (tuple(t.route), round(t.total_price))
        if sig not in seen:
            seen.add(sig)
            uniq.append(t)
    trips = uniq
    if not trips and all(options):
        errors["timing"] = "No combination fits the date windows and the time needed between legs."
    for i, opts in enumerate(options):
        if not opts:
            errors[f"leg {i + 1}"] = "No flights found for this leg in its date window."
    return PlanResult(trips=trips[: req.max_results], requests=requests, errors=errors)
