"""Virgin Australia (VA) direct from virginaustralia.com through the shared
real Chrome (see _browser.py). The booking app (Sabre Digital Experience,
book.virginaustralia.com/dx/VADX) sits behind Imperva, which answers plain
HTTP clients (even with Chrome TLS) with a 403 challenge page. Headless Chrome
gets through by itself.

We open the booking app's own flight selection deeplink and capture the
``bookingAirSearch`` GraphQL response it fetches: every flight with every
fare brand (Lite, Choice, Flex, Business) and its total price incl. taxes.
About 10 to 20 seconds per direction, headless. Round trips are priced as two
one ways (Virgin Australia prices each direction on its own)."""

from __future__ import annotations

import json
import logging
from datetime import date

from .. import cache
from ..models import Itinerary, SearchQuery
from . import _browser
from ._airline import combine, countries

log = logging.getLogger(__name__)
SITE = "https://book.virginaustralia.com/dx/VADX/"
NAMES = {"VA": "Virgin Australia"}
# Virgin Australia's own network: Australia plus short haul international
# (New Zealand, the Pacific islands, Bali) and Tokyo Haneda. Every route
# touches Australia. Its Qatar Airways wet lease flights to Doha are sold as VA.
HOME = {"AU"}
COUNTRIES = HOME | {"NZ", "FJ", "ID", "WS", "TO", "VU", "CK", "JP", "QA"}
_CABIN = {"economy": "Economy", "premium": "Economy", "business": "Business", "first": "Business"}
_BRANDS = {"LT": "Lite", "CH": "Choice", "FL": "Flex", "BU": "Business"}


def available() -> bool:
    return _browser.available()


def relevant(origins: list[str], destinations: list[str]) -> bool:
    if not available():
        return False
    o, d = countries(origins), countries(destinations)
    return bool(o and d and (o | d) <= COUNTRIES and HOME & (o | d))


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1,
             cabin: str = "economy") -> str:
    q = (f"journeyType={'round-trip' if ret else 'one-way'}&activeMonth={dep:%m-%d-%Y}&origin={origin}"
         f"&destination={dest}&date={dep:%m-%d-%Y}")
    if ret:
        q += f"&origin1={dest}&destination1={origin}&date1={ret:%m-%d-%Y}"
    q += f"&ADT={adults}&CHD=0&INF=0&class={_CABIN.get(cabin, 'Economy')}&locale=en-GB"
    return f"{SITE}#/flight-selection?{q}"


def _index(node, ids: dict) -> None:
    """Sabre answers in JSON-LD style: repeated objects are {"@ref": id}."""
    if isinstance(node, dict):
        if "@id" in node:
            ids[node["@id"]] = node
        for v in node.values():
            _index(v, ids)
    elif isinstance(node, list):
        for v in node:
            _index(v, ids)


def _amount(p: dict | None) -> float | None:
    try:
        return float(p["alternatives"][0][0]["amount"])
    except (KeyError, IndexError, TypeError):
        return None


def parse(data: dict, cabin: str = "economy", adults: int = 1) -> tuple[list[list[dict]], str | None]:
    """bookingAirSearch GraphQL response -> ([outbound journeys, return
    journeys], currency). A round trip search is "composed": one offer group
    per direction, and the round trip price is the sum of the two picks. Each
    journey keeps its cheapest available fare brand in the searched cabin.
    Sabre's totals are per adult (incl. taxes), so they are multiplied by
    ``adults``."""
    res = ((data.get("data") or {}).get("bookingAirSearch") or {}).get("originalResponse") or {}
    ids: dict = {}
    _index(res, ids)
    want = _CABIN.get(cabin, "Economy")
    currency = res.get("currency")
    bounds: list[list[dict]] = []
    for group in res.get("unbundledOffers") or []:
        best: dict[tuple, dict] = {}
        bounds.append([])
        for off in group:
            if off.get("soldout"):
                continue
            parts = off.get("itineraryPart") or []
            if not parts:
                continue
            part = parts[0]
            part = ids.get(part.get("@ref"), part) if "@ref" in part else part
            segs = [ids.get(s.get("@ref"), s) if "@ref" in s else s for s in part.get("segments") or []]
            if not segs:
                continue
            total = _amount(off.get("total")) or _amount((off.get("bundlePrice") or {}).get("total"))
            if total is None:
                continue
            if (off.get("cabinClass") or segs[0].get("cabinClass")) != want:
                continue  # Sabre returns every brand, Business included
            key = tuple((s["flight"]["airlineCode"], s["flight"]["flightNumber"], s["departure"]) for s in segs)
            if key in best and best[key]["total"] <= total * adults:
                continue
            seats = (off.get("seatsRemaining") or {}).get("count")
            best[key] = {
                "segments": [{
                    "origin": s["origin"], "destination": s["destination"],
                    "departure": s["departure"] + (s.get("departureGMTOffset") or ""),
                    "arrival": s["arrival"] + (s.get("arrivalGMTOffset") or ""),
                    "carrier": s["flight"]["airlineCode"], "number": str(s["flight"]["flightNumber"]),
                    "duration": s.get("duration"), "aircraft": s.get("equipment"),
                } for s in segs],
                "total": round(total * adults, 2), "seats": seats, "fare": off.get("brandId"),
                "duration": part.get("totalDuration"),
            }
            if not currency:
                try:
                    currency = off["total"]["alternatives"][0][0]["currency"]
                except (KeyError, IndexError, TypeError):
                    pass
        bounds[-1] = list(best.values())
    return bounds, currency


def _is_search(txt: str) -> bool:
    return '"bookingAirSearch"' in txt[:200]


def _fetch(url: str) -> dict:
    """The flight search response, or {} when there are no flights that day
    (the app then falls back to its date selection calendar)."""
    def job(page) -> tuple[str, bool]:
        page.goto("about:blank")  # a hash only change would not reload the app
        got = _browser.capture(page, lambda: page.goto(url, wait_until="commit", timeout=45000),
                               lambda u: u.endswith("/api/graphql"), timeout=50, body=_is_search,
                               stop=lambda: "/date-selection" in page.url)
        # the first one is the flight search; calendar searches may follow
        return (got[0][1] if got else ""), "/date-selection" in page.url

    txt, no_flights = _browser.run(job, "virginaustralia", timeout=120)
    d = json.loads(txt) if txt else {}
    if not ((d.get("data") or {}).get("bookingAirSearch") or {}).get("originalResponse"):
        if no_flights:
            return {}
        raise RuntimeError(f"virginaustralia: no flight search response ({json.dumps(d.get('errors'))[:200]})")
    return d


def _search(o: str, d: str, day: date, ret: date | None, adults: int, cabin: str) -> tuple[list, str | None]:
    key = f"virginaustralia:{o}:{d}:{day}:{ret}:{adults}:{cabin}"
    if (hit := cache.get(key)) is None:
        hit = _fetch(deeplink(o, d, day, ret, adults=adults, cabin=cabin))
        cache.put(key, hit)
    return parse(hit, cabin, adults) if hit else ([], None)


def search(q: SearchQuery) -> list[Itinerary]:
    if not relevant(q.origins, q.destinations):
        return []
    out: list[Itinerary] = []
    for o in q.origins[:2]:
        for d in q.destinations[:2]:
            if o == d:
                continue
            bounds, cur = _search(o, d, q.departure, q.return_date, q.adults, q.cabin)
            outs = bounds[0] if bounds else []
            backs = (bounds[1] if len(bounds) > 1 else []) if q.return_date else None
            if not outs or (q.return_date and not backs):
                continue
            out += combine(q, "virginaustralia", "Virgin Australia", outs, backs, cur or "AUD",
                           deeplink(o, d, q.departure, q.return_date, q.adults, q.cabin), NAMES,
                           note="Virgin Australia cheapest fare brand (usually Lite: carry on only).")
    return out
