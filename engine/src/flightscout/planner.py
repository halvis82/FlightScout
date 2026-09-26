"""Route planner: finds cheaper ways to get somewhere by combining separately
booked tickets through hubs, optionally with stopovers of a few days.

Strategies
* direct       the normal search (one ticket, possibly with connections)
* split        A to hub + hub to B booked separately, same day self transfer
* stopover     like split, but staying 1 to N days at the hub
* nested       round trip A to hub wrapped around a round trip hub to B
               (e.g. OSL to JFK return + JFK to SAN return)
* multicity    a whole trip through several places, built leg by leg
* nearby       leave from or land at a nearby airport when that's cheaper

Layovers come from three places: big hubs on the way, cities that real fares
say are cheap from both ends (Kiwi's "anywhere" search from each end, and the
fare memory of past searches), and gateways near either end. Each leg is
priced on Google Flights and Kiwi (a whole row of layovers per Kiwi request),
and the best combinations are then re-priced with the airlines' own sites.

Everything is priced in one currency and scored as price plus a value of time,
so a cheap but 40 hour itinerary doesn't automatically win."""

from __future__ import annotations

import itertools
import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

from pydantic import BaseModel, Field

from concurrent.futures import TimeoutError as FutureTimeout

from . import airports, farememory, fx, sellers
from .models import Itinerary, SearchQuery, Stopover, Trip
from .search import endpoint_note, merge, to_currency
from .sources import google, kiwi, kiwiweb

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
    discover_hubs: bool = True  # add layovers found from real fares (explore from both ends, fare memory)
    nearby_km: float = 200  # also try leaving from / landing at airports this close (0: off)
    reprice_with_airlines: bool = True  # re-price the best combinations on the airlines' own sites
    # fares the caller has seen (USD, cheapest per airport): origin to X and X
    # to destination, e.g. from the website's shared fare memory
    known_from_origin: dict[str, float] = Field(default_factory=dict)
    known_to_dest: dict[str, float] = Field(default_factory=dict)
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
            res = google.search(q, top_n=2 if ret else 3, wide=False)
        except Exception as e:
            self.errors[f"google {','.join(o)}-{','.join(d)} {dep}"] = str(e)[:200]
            return []
        out = [sellers.annotate(to_currency(i, self.req.currency)) for i in res]
        farememory.record(out)
        return out

    def kwindow(self, o: list[str], d: list[str], lo: date, hi: date) -> list[Itinerary]:
        """Kiwi one way tickets for up to 6 x 6 airports over a date window."""
        if not self.req.include_kiwi:
            return []
        self.requests += 1
        try:
            res = kiwiweb.search_window(o, d, lo, hi, self.req.currency, self.req.adults, self.req.cabin)
        except Exception as e:
            self.errors[f"kiwi {','.join(o)}-{','.join(d)} {lo}"] = str(e)[:200]
            return []
        out = [sellers.annotate(to_currency(i, self.req.currency)) for i in res]
        farememory.record(out)
        return out

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
    for kind in ("single", "split", "stopover", "nested", "multicity", "nearby"):
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


def _sane(it: Itinerary, max_ratio: float = 2.0) -> bool:
    """A leg that flies more than twice its own distance (San Diego to Los
    Angeles via Denver) is never what someone building a route wants."""
    for sl in it.slices:
        direct = airports.haversine_km(sl.origin, sl.destination)
        flown = sum(airports.haversine_km(g.origin, g.destination) for g in sl.segments)
        if math.isfinite(direct) and math.isfinite(flown) and direct > 0 and flown > max(direct * max_ratio, direct + 800):
            return False
    return True


def _oneway_via_hubs(ctx: _Ctx, o: list[str], d: list[str], dep: date, hubs: list[str]
                     ) -> tuple[list[Trip], dict[str, float]]:
    """o to hub on ``dep`` and hub to d on dep..dep+max_stopover_days."""
    req = ctx.req
    last = dep + timedelta(days=req.max_stopover_days)
    chunks = [hubs[i:i + 6] for i in range(0, len(hubs), 6)]
    calls: list[tuple] = [(ctx.gsearch, o, [h], dep) for h in hubs]
    for h in hubs:
        for s in range(0, req.max_stopover_days + 1):
            calls.append((ctx.gsearch, [h], d, dep + timedelta(days=s)))
    # Kiwi prices a whole row of layovers per request (its own airlines and
    # low cost carriers Google often misses)
    kiwi_first = [(ctx.kwindow, o[:6], c, dep, dep) for c in chunks]
    kiwi_second = [(ctx.kwindow, c, d[:6], dep, last) for c in chunks]
    res = ctx.many(calls + kiwi_first + kiwi_second)
    n = len(hubs)
    first_by: dict[str, list[Itinerary]] = {h: list(r) for h, r in zip(hubs, res[:n])}
    by_hub: dict[str, list[Itinerary]] = {h: [] for h in hubs}
    k = n
    for h in hubs:
        for _ in range(req.max_stopover_days + 1):
            by_hub[h].extend(res[k])
            k += 1
    for r in res[k:k + len(kiwi_first)]:
        for it in r:
            h = it.slices[-1].destination
            if h in first_by:
                first_by[h].append(it)
    for r in res[k + len(kiwi_first):]:
        for it in r:
            h = it.slices[0].origin
            if h in by_hub:
                by_hub[h].append(it)
    trips, hub_cost = [], {}
    for h in hubs:
        leg1s = [i for i in merge(first_by[h]) if _sane(i)]
        leg2s = [i for i in merge(by_hub[h]) if _sane(i)]
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


def discover_hubs(origin: str, dest: str, lo: date, hi: date, limit: int = 8,
                  max_detour: float = 1.6, known_from: dict[str, float] | None = None,
                  known_to: dict[str, float] | None = None) -> list[str]:
    """Layovers that real fares say are cheap from both ends: Kiwi's cheapest
    flight to every city from the origin and from the destination (one request
    each, cached for hours), plus the fare memory of earlier searches. A city
    cheap to fly to from both ends is usually cheap to connect through, and
    these are often places no hub list has (low cost bases, other countries
    on the way). Ranked by the two prices added up (USD)."""
    direct = airports.haversine_km(origin, dest)
    if not math.isfinite(direct) or direct < 300:
        return []
    with ThreadPoolExecutor(max_workers=2) as ex:
        fa = ex.submit(kiwiweb.explore, origin, lo, hi, "USD")
        fb = ex.submit(kiwiweb.explore, dest, lo, hi, "USD")
        a: dict[str, float] = {}
        b: dict[str, float] = {}
        for f, into in ((fa, a), (fb, b)):
            try:
                for x in f.result(timeout=40):
                    into[x.destination] = min(x.price, into.get(x.destination, x.price))
            except Exception as e:
                log.info("hub discovery: %s", e)
    # the fare memory knows exact legs: origin to X and X to dest
    for h, p in farememory.from_origin(origin, lo, hi).items():
        a[h] = min(p, a.get(h, p))
    for h, p in farememory.to_dest(dest, lo, hi + timedelta(days=3)).items():
        b[h] = min(p, b.get(h, p))
    for into, extra in ((a, known_from or {}), (b, known_to or {})):
        for h, p in extra.items():
            if isinstance(p, (int, float)) and p > 0:
                into[h.upper()] = min(float(p), into.get(h.upper(), float(p)))
    scored = []
    for h in set(a) & set(b):
        if h in (origin, dest) or not airports.get(h):
            continue
        d1, d2 = airports.haversine_km(origin, h), airports.haversine_km(h, dest)
        if d1 < 150 or d2 < 150 or (d1 + d2) / direct > max_detour:
            continue
        scored.append((a[h] + b[h], h))
    return [h for _, h in sorted(scored)[:limit]]


def _km_note(code: str, asked: str, lands: bool) -> str:
    a, b = airports.get(code), airports.get(asked)
    city = (a.city or a.name) if a else code
    km = airports.haversine_km(code, asked)
    where = (b.city or b.name) if b else asked
    return f"{'Lands at' if lands else 'Leaves from'} {code} ({city}), {km:.0f} km from {where}"


def _nearby_trips(ctx: _Ctx, o: list[str], d: list[str], dep: date, ret: date | None) -> list[Trip]:
    """Leaving from or landing at a nearby airport (a bus or train away)."""
    req = ctx.req
    if req.nearby_km <= 0:
        return []
    alt_o = [c for c in airports.nearby(o[0], req.nearby_km) if c not in o and c not in d][:4]
    alt_d = [c for c in airports.nearby(d[0], req.nearby_km) if c not in d and c not in o][:4]
    calls = []
    if alt_d:
        calls += [(ctx.gsearch, o, alt_d, dep, ret), (ctx.kwindow, o[:6], alt_d, dep, dep) if not ret else None]
    if alt_o:
        calls += [(ctx.gsearch, alt_o, d, dep, ret), (ctx.kwindow, alt_o, d[:6], dep, dep) if not ret else None]
    out = []
    for it in merge([i for r in ctx.many([c for c in calls if c]) for i in r]):
        start, end = it.slices[0].origin, it.slices[0].destination
        if ret and it.slices[-1].destination not in (start, *o, *alt_o):
            continue
        notes = []
        if start not in o:
            notes.append(_km_note(start, o[0], lands=False))
        if end not in d:
            notes.append(_km_note(end, d[0], lands=True))
        if notes:
            out.append(Trip(tickets=[it], total_price=it.price, currency=it.currency, kind="nearby",
                            note="; ".join(notes), risks=list(it.warnings)))
    return out


def _reprice(ctx: _Ctx, trips: list[Trip], limit: int = 6, wait: float = 35.0) -> list[Trip]:
    """Re-price the legs of the best split and stopover trips on the airlines'
    own sites (and the other direct sources), and swap in a cheaper leg
    wherever the connection still works."""
    from .search import search as full_search

    req = ctx.req
    best = sorted((t for t in trips if t.kind in ("split", "stopover") and len(t.tickets) <= 3),
                  key=lambda t: t.score or t.total_price)[:limit]
    legs = {(tk.slices[0].origin, tk.slices[-1].destination, tk.slices[0].departure.date())
            for t in best for tk in t.tickets if len(tk.slices) == 1}
    if not legs:
        return []

    def one(leg):
        q = SearchQuery(origins=[leg[0]], destinations=[leg[1]], departure=leg[2], currency=req.currency,
                        cabin=req.cabin, adults=req.adults, sources=["airlines"])
        ctx.requests += 1
        return full_search(q).trips

    futs = {leg: ctx.pool.submit(one, leg) for leg in list(legs)[:10]}
    alts: dict[tuple, list[Itinerary]] = {}
    end = time.monotonic() + wait
    for leg, f in futs.items():
        try:
            alts[leg] = [tr.tickets[0] for tr in f.result(timeout=max(0.1, end - time.monotonic()))]
        except FutureTimeout:
            ctx.errors[f"airlines {leg[0]}-{leg[1]} {leg[2]}"] = "airline sites were still searching"
        except Exception as e:
            ctx.errors[f"airlines {leg[0]}-{leg[1]} {leg[2]}"] = str(e)[:200]
    out = []
    for t in best:
        tickets = list(t.tickets)
        changed = False
        for i, tk in enumerate(tickets):
            key = (tk.slices[0].origin, tk.slices[-1].destination, tk.slices[0].departure.date())
            for alt in sorted(alts.get(key, []), key=lambda x: x.price):
                if alt.price >= tk.price - 0.5:
                    break
                trial = tickets[:i] + [alt] + tickets[i + 1:]
                if _chain(trial, req):
                    tickets, changed = trial, True
                    break
        if changed:
            new = _chain(tickets, req)
            if new:
                out.append(new)
    return out


def plan(req: PlanRequest) -> PlanResult:
    o = airports.expand(req.origins)
    d = airports.expand(req.destinations)
    ctx = _Ctx(req)
    main_o, main_d = o[0], d[0]
    trips: list[Trip] = []
    dep_dates = _dates(req.depart_start, req.depart_end, cap=3)
    ret_dates = _dates(req.return_start, req.return_end, cap=3) if req.return_start else []
    # Big airports near either end are always worth a try: positioning to
    # LAX from San Diego, or ending at a gateway near the destination.
    near = [g for g in airports.gateways_near(main_o) + airports.gateways_near(main_d) if g not in o and g not in d]
    static = airports.candidate_hubs(main_o, main_d, limit=req.max_hubs, extra=[h.upper() for h in req.hubs] + near)
    found = discover_hubs(main_o, main_d, dep_dates[0], dep_dates[-1] + timedelta(days=1),
                          limit=max(2, req.max_hubs // 2), known_from=req.known_from_origin,
                          known_to=req.known_to_dest) if req.discover_hubs and req.allow_self_transfer else []
    # gateways near either end first, then layovers real fares found and hubs
    # on the map taking turns; found ones get up to two extra slots
    static = [h for h in static if h not in o and h not in d]
    found = [h for h in found if h not in o and h not in d and h not in near]
    rest = [x for pair in itertools.zip_longest(found, static) for x in pair if x]
    cap = max(req.max_hubs, len(near) + 2) + min(2, len(found))
    hubs = list(dict.fromkeys(near + rest))[:cap]

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
    for i in direct_items:
        t = _single(i)
        # a "city" answer that starts or ends at another airport is a nearby trip
        if n := endpoint_note(i, o, d):
            t = t.model_copy(update={"kind": "nearby", "note": n})
        trips.append(t)

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
                best_hubs = list(dict.fromkeys(near + (sorted(hub_rank, key=hub_rank.get)[:4] or hubs[:4])))[:6]
                trips += _nested(ctx, o, d, dep_dates[0], ret_dates[0], best_hubs)

    # 4. Nearby airports at either end.
    trips += _nearby_trips(ctx, o, d, dep_dates[0], ret_dates[0] if ret_dates else None)

    trips = [t for t in trips if _travel_ok(t, req)]
    trips = sellers.apply_rules(trips, req.seller_rules)
    direct = min((t for t in trips if t.kind == "single"), key=lambda t: t.total_price, default=None)
    for t in trips:
        t.score = _score(t, req)
    # 5. The best combinations, re-priced on the airlines' own sites.
    if req.reprice_with_airlines and req.allow_self_transfer:
        better = [t for t in sellers.apply_rules(_reprice(ctx, trips), req.seller_rules) if _travel_ok(t, req)]
        for t in better:
            t.score = _score(t, req)
        trips += better
    # a nearby airport is only worth the trip across town when it saves money
    if direct:
        trips = [t for t in trips if t.kind != "nearby" or t.total_price < direct.total_price * 0.9]
    for t in trips:
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
                for it in _cheapest([sellers.annotate(to_currency(x, req.currency)) for x in opts if _sane(x)], req.beam):
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
                                              departure=sl.departure.date(), currency=req.currency), wide=False)
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
