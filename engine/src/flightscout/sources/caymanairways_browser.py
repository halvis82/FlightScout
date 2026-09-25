"""Cayman Airways (KX) direct from caymanairways.com's booking engine (Sabre
Digital Experience at flights.caymanairways.com/dx/KXDX) through the shared
real Chrome (see _browser.py). Its GraphQL API sits behind a bot manager
that tarpits plain HTTP clients and rejects requests not made by the app
itself, but headless Chrome loading the app's own search deeplink passes.

We open the flight selection deeplink and capture the ``bookingAirSearch``
GraphQL response the app makes. One response covers both directions of a
round trip (``brandedResults.itineraryPartBrands``, one list per direction,
priced per direction: the page adds the two halves up in "Trip Total").
Offers are per passenger in USD incl. taxes; economy searches use the
cheapest Economy brand (Economy Low Fare), business the cheapest Business
brand; award brands are skipped. The JSON uses @id/@ref references, resolved
here. About 9 seconds per search (the app loads fully each time).

Routes: data/caymanairways_routes.json, the app's own routes.json."""

from __future__ import annotations

import json
import logging
from datetime import date
from functools import cache as memo
from pathlib import Path

from .. import cache
from ..models import Itinerary, SearchQuery
from . import _browser
from ._airline import combine

log = logging.getLogger(__name__)
SITE = "https://flights.caymanairways.com/dx/KXDX/"
_AWARD = {"ZA", "WA", "AW"}


@memo
def routes() -> dict[str, set[str]]:
    raw = json.loads((Path(__file__).parents[1] / "data" / "caymanairways_routes.json").read_text())
    return {o: set(ds) for o, ds in raw.items()}


def available() -> bool:
    return _browser.available()


def _pairs(origins: list[str], destinations: list[str]) -> list[tuple[str, str]]:
    r = routes()
    return [(o, d) for o in origins for d in destinations if d in r.get(o, ())]


def relevant(origins: list[str], destinations: list[str]) -> bool:
    return bool(_pairs(origins, destinations)) and available()


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1) -> str:
    url = (f"{SITE}#/flight-selection?journeyType={'round-trip' if ret else 'one-way'}&locale=en-US"
           f"&awardBooking=false&searchType=BRANDED&class=Economy&ADT={adults}&CHD=0&INF=0"
           f"&origin={origin}&destination={dest}&date={dep:%m-%d-%Y}")
    if ret:
        url += f"&origin1={dest}&destination1={origin}&date1={ret:%m-%d-%Y}"
    return url


def parse(data: dict, adults: int = 1, cabin: str = "economy") -> list[list[dict]]:
    """bookingAirSearch JSON -> one list of journeys per direction."""
    resp = (((data.get("data") or {}).get("bookingAirSearch") or {}).get("originalResponse")) or data
    ids: dict[str, dict] = {}

    def walk(x):
        if isinstance(x, dict):
            if "@id" in x:
                ids[str(x["@id"])] = x
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(resp)

    def res(x):
        return ids.get(str(x["@ref"]), {}) if isinstance(x, dict) and "@ref" in x else x

    want = "Business" if cabin in ("business", "first") else "Economy"
    bounds = []
    for bound in ((resp.get("brandedResults") or {}).get("itineraryPartBrands")) or []:
        out = []
        for ipb in bound:
            ip = res(ipb.get("itineraryPart") or {})
            segs = [res(s) for s in ip.get("segments") or []]
            prices = []
            for o in ipb.get("brandOffers") or []:
                if o.get("soldout") or o.get("brandId") in _AWARD or o.get("cabinClass") != want:
                    continue
                try:
                    prices.append((float(o["total"]["alternatives"][0][0]["amount"]), o))
                except (KeyError, IndexError, TypeError):
                    continue
            if not segs or not prices:
                continue
            total, offer = min(prices, key=lambda x: x[0])
            out.append({
                "segments": [{"origin": s["origin"], "destination": s["destination"],
                              "departure": s["departure"] + (s.get("departureGMTOffset") or ""),
                              "arrival": s["arrival"] + (s.get("arrivalGMTOffset") or ""),
                              "carrier": (s.get("flight") or {}).get("airlineCode") or "KX",
                              "number": (s.get("flight") or {}).get("flightNumber"),
                              "aircraft": s.get("equipment"), "duration": s.get("duration")} for s in segs],
                "total": round(total * adults, 2), "fare": offer.get("brandId"),
                "seats": (offer.get("seatsRemaining") or {}).get("count"),
                "duration": ip.get("totalDuration"),
            })
        bounds.append(out)
    return bounds


def _fetch(url: str) -> dict:
    def job(page) -> str:
        if page.url.startswith(SITE):  # same hash route: force a fresh app load
            page.goto("about:blank")
        got = _browser.capture(page, lambda: page.goto(url, wait_until="commit", timeout=45000),
                               lambda u: "/api/graphql" in u, timeout=40,
                               body=lambda t: '"bookingAirSearch"' in t)
        return got[-1][1] if got else ""

    txt = _browser.run(job, "caymanairways", timeout=100)
    if not txt:
        raise RuntimeError("caymanairways: no search response (bot check or site change)")
    return json.loads(txt)


def search(q: SearchQuery) -> list[Itinerary]:
    pairs = _pairs(q.origins, q.destinations)
    if not pairs or not available():
        return []
    out: list[Itinerary] = []
    for o, d in pairs[:2]:
        url = deeplink(o, d, q.departure, q.return_date, q.adults)
        key = f"caymanairways:{o}:{d}:{q.departure}:{q.return_date}:{q.adults}"
        if (data := cache.get(key)) is None:
            data = _fetch(url)
            cache.put(key, data)
        bounds = parse(data, q.adults, q.cabin)
        if not bounds or (q.return_date and len(bounds) < 2):
            continue
        out += combine(q, "caymanairways", "Cayman Airways", bounds[0], bounds[1] if q.return_date else None,
                       "USD", url, {"KX": "Cayman Airways"},
                       note="Cayman Airways cheapest fare (Economy Low Fare) incl. taxes.")
    return out
