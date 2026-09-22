"""Price tracker for watchlists. Run daily (GitHub Actions) or on demand
(`flightscout watch check`). For each watch it samples the departure window,
asks Google for exact dates, asks Kiwi for the cheapest anywhere in the window
(one request covers the whole range) and optionally runs a light planner pass
for split ticket deals. Results become observations stored by the web app."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from . import airports
from .models import Itinerary, SearchQuery, Trip
from .planner import PlanRequest, plan
from .search import to_currency
from .sources import google, kiwi

log = logging.getLogger(__name__)


def _sample(start: date, end: date, n: int) -> list[date]:
    days = (end - start).days
    if days <= 0:
        return [start]
    if days + 1 <= n:
        return [start + timedelta(days=i) for i in range(days + 1)]
    return sorted({start + timedelta(days=round(i * days / (n - 1))) for i in range(n)})


def _obs(it_or_trip: Itinerary | Trip, kind: str | None = None) -> dict:
    if isinstance(it_or_trip, Trip):
        t = it_or_trip
        first = t.tickets[0]
        ret = None
        if t.kind == "single" and len(first.slices) > 1:
            ret = first.slices[1].departure.date().isoformat()
        elif len(t.tickets) > 1:
            last = max((sl for tk in t.tickets for sl in tk.slices), key=lambda s: s.departure)
            if last.destination == t.route[0]:
                ret = last.departure.date().isoformat()
        return {
            "depart_date": t.departure.date().isoformat(), "return_date": ret,
            "price": t.total_price, "currency": t.currency,
            "source": "+".join(sorted({tk.source for tk in t.tickets})),
            "kind": kind or t.kind, "route": "-".join(t.route),
            "duration_min": sum(tk.duration_min for tk in t.tickets),
            "booking_url": first.booking_url, "trip": t.model_dump(mode="json"),
        }
    it = it_or_trip
    return _obs(Trip(tickets=[it], total_price=it.price, currency=it.currency, kind="single",
                     risks=list(it.warnings)), kind)


def check(watch: dict[str, Any], budget: int = 12) -> list[dict]:
    """Return observations for one watch. ``budget`` caps Google requests."""
    cur = watch.get("currency") or "USD"
    o = airports.expand(watch["origins"])
    d = airports.expand(watch["destinations"])
    start = date.fromisoformat(watch["depart_start"])
    end = date.fromisoformat(watch.get("depart_end") or watch["depart_start"])
    today = date.today()
    if end < today:
        return []
    start = max(start, today + timedelta(days=1))
    rt = watch.get("trip_type") == "roundtrip"
    nmin = watch.get("nights_min") or 7
    nmax = watch.get("nights_max") or nmin
    cabin = watch.get("cabin") or "economy"
    out: list[dict] = []

    # Kiwi: one request covers the whole window (and the nights range).
    try:
        k = kiwi.search_range(o[0], d[0], start, end, cur, (nmin, nmax) if rt else None, cabin)
        for it in sorted(k, key=lambda i: i.price)[:5]:
            out.append(_obs(to_currency(it, cur)))
    except Exception as e:
        log.warning("kiwi failed for %s: %s", watch.get("id"), e)

    # Google: exact dates across the window.
    nights = sorted({nmin, nmax, (nmin + nmax) // 2}) if rt else [None]
    dates = _sample(start, end, max(1, budget // len(nights)))
    for dep in dates:
        for n in nights:
            q = SearchQuery(origins=o, destinations=d, departure=dep,
                            return_date=dep + timedelta(days=n) if n else None, currency=cur,
                            cabin=cabin, adults=watch.get("adults") or 1, max_stops=watch.get("max_stops"))
            try:
                res = google.search(q, top_n=2)
            except Exception as e:
                log.warning("google failed %s %s: %s", watch.get("id"), dep, e)
                continue
            if res:
                best = min((to_currency(i, cur) for i in res), key=lambda i: i.price)
                out.append(_obs(best))

    # Split tickets and stopovers on the currently cheapest date.
    if watch.get("include_split") and out:
        best = min(out, key=lambda x: x["price"])
        dep = date.fromisoformat(best["depart_date"])
        ret = date.fromisoformat(best["return_date"]) if best.get("return_date") else None
        try:
            res = plan(PlanRequest(origins=o, destinations=d, depart_start=dep, return_start=ret,
                                   currency=cur, cabin=cabin, max_hubs=4, max_stopover_days=1,
                                   include_nested_roundtrips=rt, max_results=10))
            for t in res.trips:
                if t.kind != "single":
                    out.append(_obs(t))
                    break
        except Exception as e:
            log.warning("planner failed %s: %s", watch.get("id"), e)
    return out


def _enrich_best(obs: list[dict]) -> None:
    """Add Google's seller breakdown to the cheapest Google observation when a
    browser is available (GitHub Actions installs one)."""
    try:
        from .sellers_live import enrich
    except ImportError:
        return
    g = [o for o in obs if o.get("trip") and o["source"] == "google"]
    if not g:
        return
    best = min(g, key=lambda o: o["price"])
    trip = Trip(**best["trip"])
    try:
        enrich([trip], 1)
    except Exception as e:
        log.warning("seller breakdown failed: %s", e)
        return
    best["trip"] = trip.model_dump(mode="json")


def run_all(client, only: str | None = None, budget: int = 12) -> dict[str, int]:
    """Tracker entry point: fetch every active watch, check it, push results."""
    watches = client.tracker_watches() if client.tracker_key and not client.token else client.watches()
    summary = {}
    for w in watches:
        if only and w["id"] != only:
            continue
        if not w.get("active", True):
            continue
        obs = check(w, budget=budget)
        if obs:
            _enrich_best(obs)
            if client.tracker_key and not client.token:
                client.tracker_push(w["id"], obs)
            else:
                client.push_observations(w["id"], obs)
        summary[w["id"]] = len(obs)
        log.info("watch %s: %d observations", w.get("name") or w["id"], len(obs))
    return summary
