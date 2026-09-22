"""Ryanair's public fare finder API (no key). Great for cheap European hops
and for exploring every destination from a Ryanair base."""

from __future__ import annotations

from datetime import date

import httpx

from .. import airports, cache
from ..models import Destination

BASE = "https://www.ryanair.com/api/farfnd/v4"
_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"}


def booking_url(origin: str, dest: str, dep: date, ret: date | None = None) -> str:
    u = (f"https://www.ryanair.com/gb/en/trip/flights/select?adults=1&teens=0&children=0&infants=0"
         f"&dateOut={dep.isoformat()}&originIata={origin}&destinationIata={dest}"
         f"&isReturn={'true' if ret else 'false'}")
    if ret:
        u += f"&dateIn={ret.isoformat()}"
    return u


def explore(origin: str, start: date, end: date, currency: str) -> list[Destination]:
    key = f"ryanair:{origin}:{start}:{end}:{currency}"
    if (hit := cache.get(key, ttl=6 * 3600)) is not None:
        return [Destination(**x) for x in hit]
    r = httpx.get(f"{BASE}/oneWayFares", headers=_UA, timeout=30, params={
        "departureAirportIataCode": origin, "outboundDepartureDateFrom": start.isoformat(),
        "outboundDepartureDateTo": end.isoformat(), "currency": currency, "market": "en-gb",
    })
    if r.status_code != 200:
        return []
    out = []
    for f in r.json().get("fares", []):
        o = f["outbound"]
        dest = o["arrivalAirport"]["iataCode"]
        dep = date.fromisoformat(o["departureDate"][:10])
        ap = airports.get(dest)
        out.append(Destination(
            origin=origin, destination=dest, city=o["arrivalAirport"].get("city", {}).get("name"),
            country=ap.country if ap else None, price=float(o["price"]["value"]),
            currency=o["price"]["currencyCode"], departure=dep, source="ryanair",
            booking_url=booking_url(origin, dest, dep), lat=ap.lat if ap else None,
            lon=ap.lon if ap else None,
        ))
    cache.put(key, [x.model_dump(mode="json") for x in out])
    return out
