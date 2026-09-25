"""Avianca (AV) through its own booking site in the shared headless Chrome.

booking.avianca.com (Amadeus Digital Experience) opens straight on the
availability page from a URL, and that page asks
apibooking.avianca.com/v2/search/air-bounds for the offers with a bearer
token and a bot manager header it mints itself, so we let the page make the
call and read its answer (one page load per direction, 10 to 20 seconds).

Each airBoundGroup is one journey (segments in dictionaries.flight, times
with UTC offsets) with one airBound per fare family; the cheapest one
(BASIC, "isCheapestOffer") is the "From USD 116,80" on the page:
totalPrices[0].total in minor units, for all passengers incl. taxes.
Round trips are priced as two one ways (the site sells each direction on
its own fare). Point of sale US, prices in USD.

Unofficial: fails soft."""

from __future__ import annotations

import json
from datetime import date

from .. import cache
from ..models import Itinerary, SearchQuery
from . import _browser
from ._airline import combine, countries

SITE = "https://booking.avianca.com/av/booking/avail"
NAMES = {"AV": "Avianca", "2K": "Avianca Ecuador", "LR": "Avianca Costa Rica", "TA": "Avianca El Salvador"}
_CABIN = {"economy": "economy", "premium": "economy", "business": "business", "first": "business"}
# Avianca's hubs and home markets: Colombia, Central America, Ecuador, Peru
HOME = {"CO", "SV", "GT", "CR", "EC", "PE", "HN", "NI"}


def relevant(origins: list[str], destinations: list[str]) -> bool:
    return _browser.available() and bool((countries(origins) | countries(destinations)) & HOME)


def deeplink(o: str, d: str, dep: date, ret: date | None = None, adults: int = 1, cabin: str = "economy") -> str:
    u = (f"{SITE}?departureDate={dep.isoformat()}&tripType={'round-trip' if ret else 'one-way'}&from={o}&to={d}"
         f"&nbAdults={adults}&nbYoungs=0&nbChildren=0&nbInfants=0&cabinClass={_CABIN.get(cabin, 'economy')}"
         f"&language=EN&platform=WEBB2C&pointOfSale=US")
    return u + (f"&returnDate={ret.isoformat()}" if ret else "")


def parse(data: dict) -> tuple[list[dict], str]:
    """air-bounds JSON -> (journeys for _airline.combine, currency)."""
    dic = data.get("dictionaries") or {}
    flights = dic.get("flight") or {}
    cur_info = dic.get("currency") or {}
    out, cur = [], "USD"
    for g in (data.get("data") or {}).get("airBoundGroups") or []:
        det = g.get("boundDetails") or {}
        best = None
        for b in g.get("airBounds") or []:
            tp = ((b.get("prices") or {}).get("totalPrices") or [{}])[0]
            if tp.get("total") is None:
                continue
            cur = tp.get("currencyCode") or cur
            dp = int((cur_info.get(cur) or {}).get("decimalPlaces", 2))
            price = round(tp["total"] / 10 ** dp, 2)
            seats = min((a.get("quota") or 99 for a in b.get("availabilityDetails") or []), default=None)
            if best is None or price < best[0]:
                best = (price, b.get("fareFamilyCode"), seats)
        if best is None:
            continue
        segs = []
        try:
            for s in det.get("segments") or []:
                f = flights[s["flightId"]]
                segs.append({"origin": f["departure"]["locationCode"], "destination": f["arrival"]["locationCode"],
                             "departure": f["departure"]["dateTime"], "arrival": f["arrival"]["dateTime"],
                             "carrier": f["marketingAirlineCode"],
                             "number": str(f["marketingFlightNumber"]),
                             "duration": int(f["duration"]) // 60 if f.get("duration") else None,
                             "aircraft": f.get("aircraftCode")})
        except KeyError:
            continue
        if segs:
            out.append({"segments": segs, "total": best[0], "fare": best[1], "seats": best[2],
                        "duration": int(det["duration"]) // 60 if det.get("duration") else None})
    return out, cur


def _bound(o: str, d: str, day: date, adults: int, cabin: str) -> tuple[list[dict], str]:
    key = f"avianca:{o}:{d}:{day}:{adults}:{cabin}"
    if (hit := cache.get(key)) is None:
        url = deeplink(o, d, day, None, adults, cabin)

        def job(page):
            got = _browser.capture(page, lambda: page.goto(url, wait_until="domcontentloaded", timeout=45000),
                                   lambda u: "/v2/search/air-bounds" in u, timeout=40)
            return [t for _, t in got]

        bodies = _browser.run(job, "avianca", timeout=100)
        if not bodies:
            raise RuntimeError("avianca: no availability response from booking.avianca.com (blocked?)")
        hit = json.loads(bodies[-1])
        if not (hit.get("data") or {}).get("airBoundGroups") and hit.get("errors"):
            raise RuntimeError(f"avianca: {str(hit['errors'])[:150]}")
        cache.put(key, hit)
    return parse(hit)


def search(q: SearchQuery) -> list[Itinerary]:
    if not relevant(q.origins, q.destinations):
        return []
    out: list[Itinerary] = []
    for o in q.origins[:1]:
        for d in q.destinations[:1]:
            if o == d:
                continue
            outs, cur = _bound(o, d, q.departure, q.adults, q.cabin)
            backs = None
            if q.return_date:
                if not outs:
                    continue
                backs, _ = _bound(d, o, q.return_date, q.adults, q.cabin)
                if not backs:
                    continue
            out += combine(q, "avianca", "Avianca", outs, backs, cur,
                           deeplink(o, d, q.departure, q.return_date, q.adults, q.cabin), NAMES,
                           note="Avianca's cheapest fare family (usually Basic: personal item only).")
    return out
