"""Multi city trips in a fixed order where each leg has its own date window:
"SAN to JFK around Mar 3 (±2 days), JFK to OSL any time after, OSL to CDG,
be in Paris by Mar 20, CDG to SAN". Each leg is priced as its own ticket from
Kiwi (one date range request per leg, includes connections through other
cities) and Google (full searches on the cheapest dates of the window), then a
beam search picks sequences that respect the order and leave enough time
between legs."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import date, datetime, timedelta

from pydantic import BaseModel, Field, model_validator

from . import airports, sellers
from .models import Itinerary, SearchQuery, Stopover, Trip
from .planner import PlanResult, _sane
from .search import endpoint_note, merge, to_currency
from .search import search as full_search
from .sources import google, kiwi, kiwiweb


class Leg(BaseModel):
    origins: list[str]
    destinations: list[str]
    date: date
    before: int = 0  # may depart this many days earlier
    after: int = 0  # may depart this many days later
    arrive_by: date | None = None  # must land on or before this date

    @model_validator(mode="after")
    def _sane(self) -> "Leg":
        if not self.origins or not self.destinations:
            raise ValueError("each flight needs where it leaves from and where it goes")
        if not (0 <= self.before <= 60 and 0 <= self.after <= 60):
            raise ValueError("a flight's date window is at most 60 days either way")
        self.origins = [c.strip().upper() for c in self.origins][:6]
        self.destinations = [c.strip().upper() for c in self.destinations][:6]
        return self


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

    @model_validator(mode="after")
    def _sane(self) -> "MultiRequest":
        if not 1 <= len(self.legs) <= 8:
            raise ValueError("a multi city trip has 1 to 8 flights")
        if not 1 <= self.adults <= 9:
            raise ValueError("1 to 9 adults")
        if self.cabin not in ("economy", "premium", "business", "first"):
            raise ValueError("cabin must be economy, premium, business or first")
        if not (len(self.currency) == 3 and self.currency.isalpha()):
            raise ValueError(f"{self.currency!r} is not a currency code")
        self.currency = self.currency.upper()
        self.beam = max(1, min(self.beam, 16))
        self.max_results = max(1, min(self.max_results, 50))
        return self


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
        return kiwi.search_range(o[0], d[0], lo, hi, req.currency, None, req.cabin, req.adults)

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
                                             cabin=req.cabin, adults=req.adults), top_n=1, wide=False)
        return out

    def kiwi_window():
        # every airport on both sides and the whole window, up to 100 tickets (incl. Kiwi's partners)
        return kiwiweb.search_window(o[:6], d[:6], lo, hi, req.currency, req.adults, req.cabin)

    def airlines_direct():
        # the airlines' own sites for the main day (low cost carriers Google and Kiwi miss)
        day = leg.date if lo <= leg.date <= hi else lo
        q = SearchQuery(origins=o[:4], destinations=d[:4], departure=day, currency=req.currency,
                        cabin=req.cabin, adults=req.adults, sources=["airlines"])
        return [t.tickets[0] for t in full_search(q).trips]

    ex = ThreadPoolExecutor(max_workers=4)
    jobs = {"kiwi": ex.submit(kiwi_range), "kiwiweb": ex.submit(kiwi_window), "google": ex.submit(google_best),
            "airlines": ex.submit(airlines_direct)}
    end = time.monotonic() + 60
    for name, f in jobs.items():
        try:
            found += f.result(timeout=max(0.1, end - time.monotonic()))
        except FutureTimeout:
            errors[f"{name} {o[0]}-{d[0]}"] = "still searching (skipped)"
        except Exception as e:
            errors[f"{name} {o[0]}-{d[0]}"] = str(e)[:200]
    ex.shutdown(wait=False)
    items = merge([sellers.annotate(to_currency(i, req.currency)) for i in found if _sane(i)])
    # a "city" answer that leaves from or lands at another airport says so
    for i in items:
        if (n := endpoint_note(i, o, d)) and n not in i.warnings:
            i.warnings.append(n)
    if leg.arrive_by:
        items = [i for i in items if i.slices[-1].arrival.date() <= leg.arrive_by]
    return items


def plan_multicity(req: MultiRequest) -> PlanResult:
    errors: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        options = list(ex.map(lambda lg: _leg_options(lg, req, errors), req.legs))
    requests = sum(5 for _ in req.legs)

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
