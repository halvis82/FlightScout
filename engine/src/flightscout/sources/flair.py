"""Flair Airlines (F8) direct from flyflair.com's own Next.js API routes
(/api/flair-flights/*, a proxy in front of Navitaire). Google Flights already
prices Flair and agreed with this source to the dollar in tests, so this is
mainly an airline direct seller and a check on Google's numbers.

No key and no session: plain GETs with Chrome TLS impersonation (curl_cffi)
pass Cloudflare. ``totalFare`` is the checkout total for one adult: base fare
plus HST, ATSC, airport improvement fee and carrier surcharge; the
reservation fee is listed in the breakdown and is 0 for web bookings.

Deeplink: flyflair.com has no URL based search (the booking app keeps the
search in client state), so the link opens the home page and the itinerary
carries a warning with the flight to pick."""

from __future__ import annotations

import threading
import time
from datetime import date, datetime

from curl_cffi import requests as cr

from .. import airports, cache, fx
from ..models import DatePrice, Itinerary, SearchQuery, Segment, Slice

BASE = "https://flyflair.com/api/flair-flights"
HOME = "https://flyflair.com/"
_HEADERS = {"Referer": HOME, "Accept": "application/json"}
_lock = threading.Lock()
_session: cr.Session | None = None
_last = 0.0
_MIN_GAP = 0.6  # seconds between requests, be polite

# Flair is a Canadian carrier: one end must be in Canada, the other in Canada
# or one of its sun/transborder markets.
COUNTRIES = {"CA", "US", "MX", "JM", "DO"}


def relevant(origins: list[str], destinations: list[str]) -> bool:
    def cc(codes):
        return {a.country for c in codes if (a := airports.get(c))}
    o, d = cc(origins), cc(destinations)
    return bool(o and d and (o | d) <= COUNTRIES and "CA" in (o | d))


def _get(path: str, params: dict) -> dict:
    global _session, _last
    with _lock:
        if _session is None:
            _session = cr.Session(impersonate="chrome")
        wait = _MIN_GAP - (time.time() - _last)
        if wait > 0:
            time.sleep(wait)
        _last = time.time()
    r = _session.get(f"{BASE}{path}", params=params, headers=_HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1) -> str:
    return HOME


def _flights(origin: str, dest: str, day: date, adults: int) -> list[dict]:
    key = f"flair:{origin}:{dest}:{day}:{adults}"
    if (hit := cache.get(key)) is not None:
        return hit
    d = _get("/available-flights", {
        "departureStation": origin, "arrivalStation": dest, "adultCount": adults,
        "childCount": 0, "infantCount": 0, "departureDate": day.isoformat(),
    })
    out = []
    for f in d.get("data") or []:
        if f.get("departureStation") != origin or f.get("arrivalStation") != dest or not f.get("totalFare"):
            continue
        out.append({
            "origin": origin, "destination": dest, "number": f["flightNumber"],
            "departure": f["scheduledDeparture"], "arrival": f["scheduledArrival"],
            "dep_utc": f["scheduledDepartureUtc"], "arr_utc": f["scheduledArrivalUtc"],
            "total": float(f["totalFare"]), "currency": f.get("currencyCode") or "CAD",
            "fare_class": f.get("fareClass"),
        })
    cache.put(key, out)
    return out


def _slice(f: dict) -> Slice:
    dep, arr = datetime.fromisoformat(f["departure"]), datetime.fromisoformat(f["arrival"])
    dur = int((datetime.fromisoformat(f["arr_utc"]) - datetime.fromisoformat(f["dep_utc"])).total_seconds() // 60)
    seg = Segment(origin=f["origin"], destination=f["destination"], departure=dep, arrival=arr,
                  carrier="F8", carrier_name="Flair Airlines", flight_number=f["number"], duration_min=dur)
    return Slice(segments=[seg], duration_min=max(dur, 1))


def search(q: SearchQuery) -> list[Itinerary]:
    if not relevant(q.origins, q.destinations) or q.cabin != "economy":
        return []
    out: list[Itinerary] = []
    for o in q.origins[:3]:
        for d in q.destinations[:3]:
            outs = sorted(_flights(o, d, q.departure, q.adults), key=lambda x: x["total"])[:6]
            backs = (sorted(_flights(d, o, q.return_date, q.adults), key=lambda x: x["total"])[:6]
                     if q.return_date else [None])
            for a in outs:
                for b in backs:
                    if b is not None and b["currency"] != a["currency"]:
                        continue
                    slices = [_slice(a)] + ([_slice(b)] if b else [])
                    total = a["total"] + (b["total"] if b else 0)
                    pick = f"F8 {a['number']} {a['departure'][:16]}" + (f" and F8 {b['number']} {b['departure'][:16]}" if b else "")
                    out.append(Itinerary(
                        source="flair", price=round(total, 2), currency=a["currency"], slices=slices,
                        booking_url=deeplink(o, d, q.departure, q.return_date, q.adults),
                        seller="Flair Airlines", seller_kind="airline",
                        warnings=[f"flyflair.com has no search links: search {o} to {d} there and pick {pick}."],
                    ))
    return out


def dates(origin: str, dest: str, start: date, end: date, currency: str = "CAD") -> list[DatePrice]:
    """Lowest total fare per day (same total as search), 3 weeks per call."""
    out: list[DatePrice] = []
    day = start
    while day <= end:
        key = f"flair-lf:{origin}:{dest}:{day}"
        data = cache.get(key, ttl=6 * 3600)
        if data is None:
            d = _get("/low-fares", {"departureStation": origin, "arrivalStation": dest, "adultCount": 1,
                                    "childCount": 0, "infantCount": 0, "departureDate": day.isoformat(),
                                    "daysBeforeDepartureDate": 0, "daysAfterDepartureDate": 20})
            data = (d.get("entries") or {}).get(f"{origin}-{dest}") or []
            cache.put(key, data)
        for e in data:
            dd = date.fromisoformat(e["departureDate"][:10])
            if not e.get("fare") or not (start <= dd <= end):
                continue
            price = float(e["fare"])
            if currency.upper() != "CAD":
                price = fx.convert(price, "CAD", currency)
            out.append(DatePrice(origin=origin, destination=dest, departure=dd, price=round(price, 2),
                                 currency=currency.upper(), source="flair", booking_url=HOME))
        day = day.fromordinal(day.toordinal() + 21)
    best: dict[date, DatePrice] = {}
    for x in out:
        if x.departure not in best or x.price < best[x.departure].price:
            best[x.departure] = x
    return sorted(best.values(), key=lambda x: x.departure)
