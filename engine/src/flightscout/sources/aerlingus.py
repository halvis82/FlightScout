"""Aer Lingus (EI) direct from aerlingus.com's own flight search API.

The booking app (www.aerlingus.com/app/make/flight-search-result) loads its
results from GET /api/v2/flights/fixed, a plain JSON endpoint: every flight
of the day (nonstops, connections over DUB/SNN and partner legs) with each
fare family's price per passenger incl. taxes and carrier fees. The HTML pages
sit behind Imperva, but that JSON endpoint answers a Chrome-TLS client
(curl_cffi) directly, with no key or cookie. About 1 to 2 seconds per search.

Round trips go in one request (origin=A,B&destination=B,A) and come back
split per direction; the two directions' prices add up to the round trip
fare, which is usually cheaper than two one ways. Prices are per passenger in
the point of sale currency (EUR from Ireland, GBP from the UK, USD from the
US); we multiply by the number of adults."""

from __future__ import annotations

import threading
import time
from datetime import date

from curl_cffi import requests as cr

from .. import cache
from ..models import Itinerary, SearchQuery
from ._airline import combine, countries

SITE = "https://www.aerlingus.com"
NAMES = {"EI": "Aer Lingus"}
# Aer Lingus flies Ireland (and Aer Lingus UK from Belfast/Manchester) to
# Europe, North America and the Caribbean, and sells onward connections
# through Dublin and Shannon. Every ticket touches IE, GB or US/CA.
HOME = {"IE", "GB"}
COUNTRIES = HOME | {
    "US", "CA", "BB", "MX", "JM", "DO", "PR", "BM",  # transatlantic
    "FR", "ES", "PT", "IT", "DE", "NL", "BE", "CH", "AT", "CZ", "PL", "HU", "HR", "GR", "MT", "CY", "DK",
    "NO", "SE", "FI", "TR", "SI", "JE", "GG", "IM", "IS", "LU", "BG", "RO", "EG", "MA",
}
_FARE_ORDER = ("low", "plus", "flex", "aerspace", "business", "saver", "advantage")
_lock = threading.Lock()
_session: cr.Session | None = None
_last = 0.0
_MIN_GAP = 0.8


def _sess() -> cr.Session:
    global _session
    with _lock:
        if _session is None:
            _session = cr.Session(impersonate="chrome")
        return _session


def _get(path: str, params: dict | None = None) -> dict:
    global _last
    with _lock:
        wait = _MIN_GAP - (time.time() - _last)
        if wait > 0:
            time.sleep(wait)
        _last = time.time()
    r = _sess().get(f"{SITE}{path}", params=params, timeout=40,
                    headers={"Accept": "application/json", "Referer": f"{SITE}/app/make/flight-search-result"})
    r.raise_for_status()
    return r.json()


def relevant(origins: list[str], destinations: list[str]) -> bool:
    o, d = countries(origins), countries(destinations)
    if not (o and d and (o | d) <= COUNTRIES):
        return False
    na = {"US", "CA", "BB", "MX", "JM", "DO", "PR", "BM"}
    return bool(HOME & (o | d)) or bool((o & na) and d - na) or bool((d & na) and o - na)


def destinations(origin: str) -> set[str] | None:
    """Airports Aer Lingus sells from ``origin`` (the booker's own list)."""
    key = f"aerlingus:dest:{origin}"
    if (hit := cache.get(key, ttl=3 * 86400)) is not None:
        return set(hit)
    try:
        data = _get("/service/planpage/destinations", {"flow": "MAKE", "tripType": "SINGLE", "origin": origin})
        dests = sorted({c for x in data.get("data") or [] for c in x.get("destinations") or []})
    except Exception:
        return None  # let the search decide
    cache.put(key, dests)
    return set(dests)


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1) -> str:
    q = (f"fareType={'RETURN' if ret else 'ONEWAY'}&fareCategory=ECONOMY&promoCode=&numAdults={adults}"
         f"&numYoungAdults=0&numChildren=0&numInfants=0&groupBooking=false"
         f"&sourceAirportCode_0={origin}&destinationAirportCode_0={dest}&departureDate_0={dep.isoformat()}")
    if ret:
        q += f"&sourceAirportCode_1={dest}&destinationAirportCode_1={origin}&departureDate_1={ret.isoformat()}"
    return f"{SITE}/app/make/flight-search-result?{q}"


def _mins(s: str | None) -> int | None:
    if not s:
        return None
    h, _, m = s.replace("m", "").partition("h")
    return int(h or 0) * 60 + int(m or 0)


def parse(data: dict, adults: int = 1, cabin: str = "ECONOMY") -> tuple[list[dict], list[dict], str]:
    """/api/v2/flights/fixed JSON -> (outbound journeys, inbound journeys,
    currency). Each journey keeps its cheapest fare in ``cabin``."""
    d = data.get("data") or {}
    cur = (d.get("attributes") or {}).get("currency") or "EUR"
    out: dict[str, list[dict]] = {}
    for way in ("outbound", "inbound"):
        js = []
        for f in ((d.get("journey") or {}).get(way) or {}).get("flights") or []:
            fares = [x for x in (f.get("priceInfo") or {}).get("fares") or []
                     if x.get("price") is not None and (x.get("cabin") or "ECONOMY") == cabin and (x.get("seats") is None or x["seats"] > 0)]
            if not fares or not f.get("trips"):
                continue
            best = min(fares, key=lambda x: float(x["price"]))
            segs = [{
                "origin": t["departure"]["airportCode"], "destination": t["arrival"]["airportCode"],
                "departure": t["departure"]["date"], "arrival": t["arrival"]["date"],
                "carrier": (t.get("info") or {}).get("carrierAirlineCode") or "EI",
                "number": (t.get("info") or {}).get("number"), "duration": _mins(t.get("duration")),
                "aircraft": (t.get("info") or {}).get("aircraftType"),
            } for t in f["trips"]]
            js.append({"segments": segs, "total": round(float(best["price"]) * adults, 2), "fare": best.get("type"),
                       "seats": best.get("seats"), "duration": _mins(f.get("totalDuration"))})
        out[way] = js
    return out["outbound"], out["inbound"], cur


def _fetch(o: str, d: str, dep: date, ret: date | None, adults: int) -> dict:
    key = f"aerlingus:{o}:{d}:{dep}:{ret}:{adults}"
    if (hit := cache.get(key)) is not None:
        return hit
    p = {"origin": f"{o},{d}" if ret else o, "destination": f"{d},{o}" if ret else d,
         "departureDate": f"{dep:%d/%m/%Y}", "numYouths": 0, "numAdults": adults, "numChildren": 0,
         "numInfants": 0, "fare": "low"}
    if ret:
        p["returnDate"] = f"{ret:%d/%m/%Y}"
    data = _get("/api/v2/flights/fixed", p)
    cache.put(key, data)
    return data


def search(q: SearchQuery) -> list[Itinerary]:
    if not relevant(q.origins, q.destinations):
        return []
    cabin = "BUSINESS" if q.cabin in ("business", "first") else "ECONOMY"
    out: list[Itinerary] = []
    for o in q.origins[:3]:
        dests = destinations(o)
        for d in q.destinations[:3]:
            if o == d or (dests is not None and d not in dests):
                continue
            outs, backs, cur = parse(_fetch(o, d, q.departure, q.return_date, q.adults), q.adults, cabin)
            if not outs or (q.return_date and not backs):
                continue
            # the API returns local wall clock times with no offset
            out += combine(q, "aerlingus", "Aer Lingus", outs, backs if q.return_date else None, cur,
                           deeplink(o, d, q.departure, q.return_date, q.adults), NAMES,
                           note="Aer Lingus cheapest fare (Saver/Low: carry-on only, checked bags extra)."
                           if cabin == "ECONOMY" else None)
    return out
