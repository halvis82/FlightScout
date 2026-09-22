"""Route planner: finds cheaper ways to get somewhere by combining separately
booked tickets through hubs, optionally with stopovers of a few days.

Strategies
* direct       the normal search (one ticket, possibly with connections)
* split        A to hub + hub to B booked separately, same day self transfer
* stopover     like split, but staying 1 to N days at the hub
* nested       round trip A to hub wrapped around a round trip hub to B
               (e.g. OSL to JFK return + JFK to SAN return)
* multicity    a whole trip through several places, built leg by leg

Everything is priced in one currency and scored as price plus a value of time,
so a cheap but 40 hour itinerary doesn't automatically win."""

from __future__ import annotations

import itertools
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

from pydantic import BaseModel, Field

from . import airports, fx, sellers
from .models import Itinerary, SearchQuery, Stopover, Trip
from .search import merge, to_currency
from .sources import google, kiwi

log = logging.getLogger(__name__)

SPLIT_RISK = ("Separate tickets: if the first flight is late and you miss the next one, "
              "the second airline owes you nothing. Leave a buffer and avoid checked bags.")


class PlanRequest(BaseModel):
    origins: list[str]
    destinations: list[str]
    depart_start: date
    depart_end: date | None = None
    return_start: date | None = None
    return_end: date | None = None
    currency: str = "USD"
    cabin: str = "economy"
    adults: int = 1
    max_stopover_days: int = 3
    min_connection_hours: float = 3.0
    max_trip_days: int | None = None
    max_travel_hours: float | None = None  # per direction, excluding stopovers
    hubs: list[str] = Field(default_factory=list)  # always try these
    max_hubs: int = 10
    allow_self_transfer: bool = True
    include_nested_roundtrips: bool = True
    include_kiwi: bool = True
    value_of_time_per_hour: float = 15.0  # in `currency`, used for scoring only
    max_results: int = 40
    seller_rules: dict[str, str] | None = None


class PlanResult(BaseModel):
    trips: list[Trip]
    direct: Trip | None = None
    hubs_tried: list[str] = Field(default_factory=list)
    requests: int = 0
    errors: dict[str, str] = Field(default_factory=dict)


class _Ctx:
    def __init__(self, req: PlanRequest):
        self.req = req
        self.requests = 0
        self.errors: dict[str, str] = {}
        self.pool = ThreadPoolExecutor(max_workers=8)

    def gsearch(self, o: list[str], d: list[str], dep: date, ret: date | None = None) -> list[Itinerary]:
        self.requests += 1
        q = SearchQuery(origins=o, destinations=d, departure=dep, return_date=ret,
                        currency=self.req.currency, cabin=self.req.cabin, adults=self.req.adults)
        try:
            res = google.search(q, top_n=2 if ret else 3)
        except Exception as e:
            self.errors[f"google {','.join(o)}-{','.join(d)} {dep}"] = str(e)[:200]
            return []
        return [sellers.annotate(to_currency(i, self.req.currency)) for i in res]

    def ksearch(self, o: list[str], d: list[str], dep: date, ret: date | None = None) -> list[Itinerary]:
        if not self.req.include_kiwi:
            return []
        self.requests += 1
        q = SearchQuery(origins=o, destinations=d, departure=dep, return_date=ret,
                        currency=self.req.currency, cabin=self.req.cabin, adults=self.req.adults)
        try:
            res = kiwi.search(q)
        except Exception as e:
            self.errors[f"kiwi {','.join(o)}-{','.join(d)} {dep}"] = str(e)[:200]
            return []
        return [sellers.annotate(to_currency(i, self.req.currency)) for i in res]

    def many(self, calls: list[tuple]) -> list[list[Itinerary]]:
        futs = [self.pool.submit(fn, *args) for fn, *args in calls]
        return [f.result() for f in futs]


def _dates(start: date, end: date | None, cap: int = 3) -> list[date]:
    end = end or start
    n = (end - start).days + 1
    if n <= cap:
        return [start + timedelta(days=i) for i in range(n)]
    step = (n - 1) / (cap - 1)
    return sorted({start + timedelta(days=round(i * step)) for i in range(cap)})


def _hours(a: datetime, b: datetime) -> float:
    return (b - a).total_seconds() / 3600


def _score(t: Trip, req: PlanRequest) -> float:
    travel_h = sum(tk.duration_min for tk in t.tickets) / 60
    penalty = 0.0
    if len(t.tickets) > 1:
        penalty += 20 * (len(t.tickets) - 1)  # hassle of separate tickets
    if any(tk.self_transfer for tk in t.tickets):
        penalty += 15
    return round(t.total_price + req.value_of_time_per_hour * travel_h + penalty, 2)


def select(trips: list[Trip], max_results: int) -> list[Trip]:
    """Dedupe near identical trips and keep a diverse set: the best few of each
    kind plus the overall best by score and by price."""
    best: dict[tuple, Trip] = {}
    for t in trips:
        sig = (t.kind, tuple(t.route), round(t.total_price), t.departure.date())
        if sig not in best or (t.score or 0) < (best[sig].score or 0):
            best[sig] = t
    uniq = list(best.values())
    picked: dict[str, Trip] = {}
    for kind in ("single", "split", "stopover", "nested", "multicity"):
        for t in sorted((t for t in uniq if t.kind == kind), key=lambda t: t.score or 0)[:6]:
            picked[t.id] = t
    for t in sorted(uniq, key=lambda t: t.score or 0)[: max_results // 2]:
        picked[t.id] = t
    for t in sorted(uniq, key=lambda t: t.total_price)[: max_results // 2]:
        picked[t.id] = t
    return sorted(picked.values(), key=lambda t: t.score or 0)[:max_results]


def _single(it: Itinerary) -> Trip:
    return Trip(tickets=[it], total_price=it.price, currency=it.currency, kind="single",
                risks=list(it.warnings))


def _chain(legs: list[Itinerary], req: PlanRequest, kind: str | None = None) -> Trip | None:
    """Combine one way tickets flown in sequence. Returns None when the gaps
    don't work (too tight or longer than the stopover limit)."""
    stopovers, risks = [], []
    for a, b in zip(legs, legs[1:]):
        arr, dep = a.slices[-1].arrival, b.slices[0].departure
        gap = _hours(arr, dep)
        if a.slices[-1].destination != b.slices[0].origin:
            return None
        if gap < req.min_connection_hours:
            return None
        if gap > req.max_stopover_days * 24 + 18:
            return None
        if gap >= 20:
            stopovers.append(Stopover(airport=b.slices[0].origin, hours=round(gap, 1)))
    risks.append(SPLIT_RISK)
    for tk in legs:
        risks.extend(tk.warnings)
    k = kind or ("stopover" if stopovers else "split")
    return Trip(tickets=legs, total_price=round(sum(t.price for t in legs), 2), currency=req.currency,
                kind=k, stopovers=stopovers, risks=list(dict.fromkeys(risks)))


def _travel_ok(t: Trip, req: PlanRequest) -> bool:
    if req.max_travel_hours is None:
        return True
    # compare per direction: sum outbound slices before the destination
    out = sum(tk.slices[0].duration_min for tk in t.tickets if tk.slices) / 60
    return out <= req.max_travel_hours * (2 if t.kind == "nested" else 1) + 1e-6


def _cheapest(items: list[Itinerary], n: int) -> list[Itinerary]:
    return sorted(items, key=lambda i: i.price)[:n]


def _oneway_via_hubs(ctx: _Ctx, o: list[str], d: list[str], dep: date, hubs: list[str]
                     ) -> tuple[list[Trip], dict[str, float]]:
    """o to hub on ``dep`` and hub to d on dep..dep+max_stopover_days."""
    req = ctx.req
    first = ctx.many([(ctx.gsearch, o, [h], dep) for h in hubs])
    second_calls, keys = [], []
    for h in hubs:
        for s in range(0, req.max_stopover_days + 1):
            second_calls.append((ctx.gsearch, [h], d, dep + timedelta(days=s)))
            keys.append(h)
    second = ctx.many(second_calls)
    by_hub: dict[str, list[Itinerary]] = {h: [] for h in hubs}
    for h, res in zip(keys, second):
        by_hub[h].extend(res)
    trips, hub_cost = [], {}
    for h, leg1s in zip(hubs, first):
        leg2s = by_hub[h]
        if leg1s and leg2s:
            hub_cost[h] = min(i.price for i in leg1s) + min(i.price for i in leg2s)
        for a in _cheapest(leg1s, 5):
            for b in _cheapest(leg2s, 12):
                t = _chain([a, b], req)
                if t:
                    trips.append(t)
    return trips, hub_cost


def _nested(ctx: _Ctx, o: list[str], d: list[str], dep: date, ret: date, hubs: list[str]) -> list[Trip]:
    """Round trip o to hub around a round trip hub to d."""
    req = ctx.req
    k = min(2, req.max_stopover_days)
    variants = {(0, 0), (k, 0), (0, k), (k, k)} if k else {(0, 0)}
    calls, meta = [], []
    for h in hubs:
        for s1, s2 in variants:
            inner_dep, inner_ret = dep + timedelta(days=s1), ret
            outer_ret = ret + timedelta(days=s2)
            if inner_ret <= inner_dep:
                continue
            calls.append((ctx.gsearch, o, [h], dep, outer_ret))
            calls.append((ctx.gsearch, [h], d, inner_dep, inner_ret))
            meta.append(h)
    res = ctx.many(calls)
    trips = []
    for i, h in enumerate(meta):
        outer, inner = res[2 * i], res[2 * i + 1]
        for a in _cheapest(outer, 3):
            for b in _cheapest(inner, 3):
                # a: o->h, h->o ; b: h->d, d->h. Check both hub connections.
                g1 = _hours(a.slices[0].arrival, b.slices[0].departure)
                g2 = _hours(b.slices[1].arrival, a.slices[1].departure)
                lim = req.max_stopover_days * 24 + 18
                if not (req.min_connection_hours <= g1 <= lim and req.min_connection_hours <= g2 <= lim):
                    continue
                stops = [Stopover(airport=h, hours=round(g, 1)) for g in (g1, g2) if g >= 20]
                risks = [SPLIT_RISK, f"Two round trip tickets nested at {h}. Missing the first "
                         "flight of either ticket can cancel the rest of that ticket."]
                for tk in (a, b):
                    risks.extend(tk.warnings)
                trips.append(Trip(tickets=[a, b], total_price=round(a.price + b.price, 2),
                                  currency=req.currency, kind="nested", stopovers=stops,
                                  risks=list(dict.fromkeys(risks))))
    return trips


def plan(req: PlanRequest) -> PlanResult:
    o = airports.expand(req.origins)
    d = airports.expand(req.destinations)
    ctx = _Ctx(req)
    main_o, main_d = o[0], d[0]
    hubs = airports.candidate_hubs(main_o, main_d, limit=req.max_hubs, extra=[h.upper() for h in req.hubs])
    hubs = [h for h in hubs if h not in o and h not in d]
    trips: list[Trip] = []
    dep_dates = _dates(req.depart_start, req.depart_end, cap=3)
    ret_dates = _dates(req.return_start, req.return_end, cap=3) if req.return_start else []

    # 1. Direct (single ticket) options.
    direct_calls = []
    for dep in dep_dates:
        if ret_dates:
            for ret in ret_dates:
                if ret > dep and (not req.max_trip_days or (ret - dep).days <= req.max_trip_days):
                    direct_calls += [(ctx.gsearch, o, d, dep, ret), (ctx.ksearch, o, d, dep, ret)]
        else:
            direct_calls += [(ctx.gsearch, o, d, dep), (ctx.ksearch, o, d, dep)]
    direct_items = merge([i for r in ctx.many(direct_calls) for i in r])
    trips += [_single(i) for i in direct_items]

    if req.allow_self_transfer and hubs:
        # 2. One way through hubs (outbound, and inbound for round trips).
        hub_rank: dict[str, float] = {}
        outs: list[Trip] = []
        for dep in dep_dates[:2]:
            t, cost = _oneway_via_hubs(ctx, o, d, dep, hubs)
            outs += t
            for h, c in cost.items():
                hub_rank[h] = min(c, hub_rank.get(h, float("inf")))
        if not ret_dates:
            trips += outs
        else:
            backs: list[Trip] = []
            for ret in ret_dates[:2]:
                t, _ = _oneway_via_hubs(ctx, d, o, ret, hubs)
                backs += t
            # one way singles for each direction too, so we can mix e.g. a
            # direct outbound with a split return
            ow_out = [_single(i) for r in ctx.many([(ctx.gsearch, o, d, x) for x in dep_dates[:2]]) for i in r]
            ow_back = [_single(i) for r in ctx.many([(ctx.gsearch, d, o, x) for x in ret_dates[:2]]) for i in r]
            out_pool = sorted(outs + ow_out, key=lambda t: t.total_price)[:15]
            back_pool = sorted(backs + ow_back, key=lambda t: t.total_price)[:15]
            for a, b in itertools.product(out_pool, back_pool):
                if b.departure <= a.arrival:
                    continue
                if req.max_trip_days and (b.arrival.date() - a.departure.date()).days > req.max_trip_days:
                    continue
                kind = "split" if len(a.tickets) + len(b.tickets) > 2 or a.kind != "single" or b.kind != "single" else "split"
                trips.append(Trip(
                    tickets=a.tickets + b.tickets, total_price=round(a.total_price + b.total_price, 2),
                    currency=req.currency,
                    kind="stopover" if (a.stopovers or b.stopovers) else kind,
                    stopovers=a.stopovers + b.stopovers,
                    risks=list(dict.fromkeys([SPLIT_RISK] + a.risks + b.risks)),
                ))
            # 3. Nested round trips through the most promising hubs.
            if req.include_nested_roundtrips:
                best_hubs = sorted(hub_rank, key=hub_rank.get)[:4] or hubs[:4]
                trips += _nested(ctx, o, d, dep_dates[0], ret_dates[0], best_hubs)

    trips = [t for t in trips if _travel_ok(t, req)]
    trips = sellers.apply_rules(trips, req.seller_rules)
    direct = min((t for t in trips if t.kind == "single"), key=lambda t: t.total_price, default=None)
    for t in trips:
        t.score = _score(t, req)
        if direct and t.kind != "single":
            t.savings_vs_direct = round(direct.total_price - t.total_price, 2)
    final = select(trips, req.max_results)
    ctx.pool.shutdown(wait=False)
    return PlanResult(trips=final, direct=direct, hubs_tried=hubs, requests=ctx.requests, errors=ctx.errors)


# ---------------------------------------------------------------------------
# Multi city trip builder
# ---------------------------------------------------------------------------

class TripStop(BaseModel):
    place: str  # airport or metro code
    min_nights: int = 2
    max_nights: int = 5


class TripRequest(BaseModel):
    start: str  # home airport
    end: str | None = None  # defaults to start
    stops: list[TripStop]
    earliest_departure: date
    latest_departure: date | None = None
    max_trip_days: int | None = None
    keep_order: bool = False
    currency: str = "USD"
    beam: int = 4
    value_of_time_per_hour: float = 15.0


def _order(req: TripRequest) -> list[list[TripStop]]:
    """Candidate visiting orders: the given order, plus a few short tours by
    distance when the user allows reordering."""
    if req.keep_order or len(req.stops) <= 1:
        return [req.stops]
    end = req.end or req.start

    def length(seq: list[TripStop]) -> float:
        codes = [req.start] + [airports.expand(s.place)[0] for s in seq] + [end]
        return sum(airports.haversine_km(a, b) for a, b in zip(codes, codes[1:]))

    if len(req.stops) <= 6:
        perms = sorted(itertools.permutations(req.stops), key=length)
        return [list(p) for p in perms[:3]]
    return [req.stops]


def build_trip(req: TripRequest) -> PlanResult:
    """Beam search over legs. Each leg uses Kiwi's date range search (one
    request covers the whole allowed window), then the best final plans are
    re-priced on Google Flights for the exact dates when possible."""
    end = req.end or req.start
    errors: dict[str, str] = {}
    requests = 0
    results: list[Trip] = []
    last = req.latest_departure or req.earliest_departure + timedelta(days=3)
    for seq in _order(req):
        codes = [s.place for s in seq] + [end]
        # beam entries: (tickets, arrival datetime, cost)
        beam: list[tuple[list[Itinerary], datetime | None, float]] = [([], None, 0.0)]
        prev = req.start
        for i, dest in enumerate(codes):
            nxt = []
            for tickets, arr, cost in beam:
                if arr is None:
                    lo, hi = req.earliest_departure, last
                else:
                    st = seq[i - 1]
                    lo = arr.date() + timedelta(days=st.min_nights)
                    hi = arr.date() + timedelta(days=st.max_nights)
                try:
                    requests += 1
                    opts = kiwi.search_range(prev, dest, lo, hi, req.currency)
                except Exception as e:
                    errors[f"{prev}-{dest}"] = str(e)[:200]
                    opts = []
                for it in _cheapest([sellers.annotate(to_currency(x, req.currency)) for x in opts], req.beam):
                    if arr and it.slices[0].departure <= arr:
                        continue
                    nxt.append((tickets + [it], it.slices[-1].arrival, cost + it.price))
            beam = sorted(nxt, key=lambda b: b[2])[: req.beam]
            prev = dest
            if not beam:
                break
        for tickets, _, cost in beam:
            if len(tickets) != len(codes):
                continue
            days = (tickets[-1].slices[-1].arrival.date() - tickets[0].slices[0].departure.date()).days
            if req.max_trip_days and days > req.max_trip_days:
                continue
            stops = [Stopover(airport=a.slices[-1].destination, hours=round(_hours(a.slices[-1].arrival, b.slices[0].departure), 1))
                     for a, b in zip(tickets, tickets[1:])]
            risks = ["Each flight is a separate ticket. Changes on one don't carry over to the others."]
            for tk in tickets:
                risks.extend(tk.warnings)
            t = Trip(tickets=tickets, total_price=round(cost, 2), currency=req.currency, kind="multicity",
                     stopovers=stops, risks=list(dict.fromkeys(risks)))
            t.score = round(cost + req.value_of_time_per_hour * sum(tk.duration_min for tk in tickets) / 60, 2)
            results.append(t)

    # Re-price winners on Google for the exact same dates (airline direct
    # links are nicer than an OTA when the price is comparable).
    results.sort(key=lambda t: t.score or 0)
    for t in results[:2]:
        new_tickets = []
        for tk in t.tickets:
            sl = tk.slices[0]
            try:
                requests += 1
                g = google.search(SearchQuery(origins=[sl.origin], destinations=[sl.destination],
                                              departure=sl.departure.date(), currency=req.currency))
                g = [to_currency(x, req.currency) for x in g]
                alt = min(g, key=lambda x: x.price, default=None)
            except Exception as e:
                errors[f"google {sl.origin}-{sl.destination}"] = str(e)[:200]
                alt = None
            new_tickets.append(sellers.annotate(alt) if alt and alt.price <= tk.price * 1.05 else tk)
        if any(a is not b for a, b in zip(new_tickets, t.tickets)):
            total = round(sum(x.price for x in new_tickets), 2)
            results.append(t.model_copy(update={"tickets": new_tickets, "total_price": total,
                                                "score": (t.score or 0) - t.total_price + total}))
    results = list({t.id: t for t in results}.values())
    results.sort(key=lambda t: t.score or 0)
    return PlanResult(trips=results[:20], requests=requests, errors=errors)
