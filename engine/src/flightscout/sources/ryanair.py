"""Ryanair's public fare finder API (no key). Great for cheap European hops
and for exploring every destination from a Ryanair base.

search(): the cheapest Ryanair flight of the day on a route, with its times
and flight number, from the fare finder (the booking API itself refuses non
browser clients). The price is the one Ryanair's flight selection shows for
that flight (the basic fare), for all passengers: the fare finder picks a
flight with enough seats for the whole party. We ask in the currency Ryanair
charges from the departure airport and convert with our own daily rates, since
Ryanair's own currency conversion adds a markup."""

from __future__ import annotations

from datetime import date, timedelta

import httpx

from .. import airports, cache
from ..models import Destination, Itinerary, SearchQuery
from ._airline import combine

BASE = "https://www.ryanair.com/api/farfnd/v4"
_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"}


def booking_url(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1) -> str:
    u = (f"https://www.ryanair.com/gb/en/trip/flights/select?adults={adults}&teens=0&children=0&infants=0"
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


def _airports() -> dict[str, str]:
    """Ryanair airports: IATA code to the currency charged there."""
    key = "ryanair:airports"
    if (hit := cache.get(key, ttl=7 * 86400)) is not None:
        return hit
    r = httpx.get("https://www.ryanair.com/api/views/locate/5/airports/en/active", headers=_UA, timeout=30)
    r.raise_for_status()
    out = {a["code"]: (a.get("country") or {}).get("currency") or "EUR" for a in r.json() if a.get("code")}
    cache.put(key, out)
    return out


def relevant(origins: list[str], destinations: list[str]) -> bool:
    try:
        known = _airports()
    except Exception:
        return False
    return any(o in known for o in origins) and any(d in known for d in destinations)


def _cheapest(origin: str, dest: str, day: date, adults: int, currency: str) -> dict | None:
    key = f"ryanair:day:{origin}:{dest}:{day}:{adults}:{currency}"
    if (hit := cache.get(key)) is not None:
        return hit or None
    r = httpx.get(f"{BASE}/oneWayFares", headers=_UA, timeout=30, params={
        "departureAirportIataCode": origin, "arrivalAirportIataCode": dest,
        "outboundDepartureDateFrom": day.isoformat(), "outboundDepartureDateTo": day.isoformat(),
        "currency": currency, "market": "en-gb", "adultPaxCount": adults,
    })
    r.raise_for_status()
    fares = r.json().get("fares") or []
    j = None
    if fares:
        o = fares[0]["outbound"]
        num = o.get("flightNumber") or "FR"
        j = {"segments": [{"origin": origin, "destination": dest, "departure": o["departureDate"],
                           "arrival": o["arrivalDate"], "carrier": num[:2], "number": num[2:]}],
             "total": float(o["price"]["value"]), "seats": None, "currency": o["price"]["currencyCode"]}
    cache.put(key, j or {})
    return j


def search(q: SearchQuery) -> list[Itinerary]:
    if q.cabin != "economy":
        return []
    known = _airports()
    pairs = [(o, d) for o in q.origins if o in known for d in q.destinations if d in known and d != o][:4]
    out: list[Itinerary] = []
    days = [q.departure + timedelta(days=k) for k in range(-min(q.departure_flex_days, 2), min(q.departure_flex_days, 2) + 1)]
    for o, d in pairs:
        cur = known[o]
        for day in days:
            if day < date.today():
                continue
            a = _cheapest(o, d, day, q.adults, cur)
            if not a:
                continue
            b = None
            if q.return_date:
                b = _cheapest(d, o, q.return_date, q.adults, known[d])
                if not b:
                    continue
                if b["currency"] != a["currency"]:  # each way is charged in its own country's money
                    from .. import fx
                    b = {**b, "total": round(fx.convert(b["total"], b["currency"], a["currency"]), 2)}
            out += combine(q, "ryanair", "Ryanair", [a], [b] if b else None, a["currency"],
                           booking_url(o, d, day, q.return_date, q.adults), {"FR": "Ryanair", "RK": "Ryanair UK",
                                                                    "AL": "Malta Air", "RR": "Buzz"},
                           note="Ryanair's basic fare: a small bag only, seats and bigger bags cost extra.")
    return out
