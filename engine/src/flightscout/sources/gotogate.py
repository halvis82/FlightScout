"""Gotogate (and its sister brand Mytrip, see mytrip.py), both Etraveli
Group OTAs, through the GraphQL endpoint their own result page calls
(POST /graphql/SearchOnResultPage, keyless, Chrome TLS impersonation). About
one second per request, live fares, prices in minor units per traveler.

The site treats an airport code as its whole city (BCN-LHR also returns
Stansted and Luton), so we ask for the cheapest trips, the cheapest direct
ones, and one more page, then keep only the requested airports. Trips tagged
VIRTUAL_INTERLINING are self transfer combinations built by Etraveli.

The market (and so the currency) comes from the domain: www.gotogate.com
prices in USD, uk.gotogate.com in GBP, and so on (see DOMAINS). Anything else
uses the USD site and search() converts."""

from __future__ import annotations

import json
import threading
from datetime import datetime

from curl_cffi import requests as cr

from .. import cache
from ..models import Itinerary, SearchQuery, Segment, Slice

BRANDS = {
    "gotogate": ("Gotogate", {"USD": "www.gotogate.com", "GBP": "uk.gotogate.com", "EUR": "www.gotogate.fr",
                              "NOK": "www.gotogate.no", "SEK": "www.gotogate.se", "CAD": "ca.gotogate.com",
                              "AUD": "au.gotogate.com"}),
    "mytrip": ("Mytrip", {"USD": "www.mytrip.com", "GBP": "uk.mytrip.com", "NOK": "no.mytrip.com",
                          "SEK": "se.mytrip.com", "CAD": "ca.mytrip.com", "AUD": "au.mytrip.com"}),
}
_CABIN = {"economy": "ECONOMY", "premium": "PREMIUM", "business": "BUSINESS", "first": "FIRST"}
Q = """query SearchOnResultPage($routes: [Route!]!, $cabinClass: CabinClass, $direct: Boolean, $adults: Int!,
  $childAges: [Int], $offset: Int, $sortTypeCode: String) {
 search(routes: $routes, cabinClass: $cabinClass, direct: $direct, adults: $adults, childAges: $childAges,
        offset: $offset, sortTypeCode: $sortTypeCode) {
  flightsCount searchPath
  flights { id selectionKey shareableUrl tripCharacteristics
   bounds { segments {
     ... on TripSegment { __typename departuredAt arrivedAt duration flightNumber
       marketingCarrier { code name } operatingCarrier { code name }
       origin { code } destination { code } segmentDetails { paxType numberOfSeatsLeft } }
     ... on EventSegment { __typename types duration } } }
   travelerPrices { price { price { value currency { code } } } }
  } } }"""
_local = threading.local()


def relevant(origins: list[str], destinations: list[str]) -> bool:
    return True  # a global OTA


def _session() -> cr.Session:
    if not hasattr(_local, "s"):
        _local.s = cr.Session(impersonate="chrome")
    return _local.s


def domain(brand: str, currency: str) -> str:
    doms = BRANDS[brand][1]
    return doms.get(currency.upper(), doms["USD"])


def _variables(q: SearchQuery, o: str, d: str, direct: bool, offset: int) -> dict:
    routes = [{"origin": o, "destination": d, "departureDate": q.departure.isoformat()}]
    if q.return_date:
        routes.append({"origin": d, "destination": o, "departureDate": q.return_date.isoformat()})
    return {"routes": routes, "adults": q.adults, "childAges": [], "cabinClass": _CABIN.get(q.cabin, "ECONOMY"),
            "direct": direct, "offset": offset, "sortTypeCode": "CHEAP_TRIP"}


def _post(host: str, v: dict) -> dict:
    key = f"etraveli:{host}:" + json.dumps(v, sort_keys=True)
    if (hit := cache.get(key, ttl=1800)) is not None:
        return hit
    s = _session()
    seen = _local.__dict__.setdefault("hosts", set())
    if host not in seen:  # session cookies, as a browser would have
        s.get(f"https://{host}/", timeout=25)
        seen.add(host)
    r = s.post(f"https://{host}/graphql/SearchOnResultPage", timeout=60,
               json={"operationName": "SearchOnResultPage", "variables": v, "query": Q},
               headers={"Origin": f"https://{host}", "Referer": f"https://{host}/result", "Accept": "*/*"})
    if r.status_code != 200:
        raise RuntimeError(f"{host}: HTTP {r.status_code}")
    body = r.json()
    if body.get("errors") and not (body.get("data") or {}).get("search"):
        raise RuntimeError(f"{host}: " + str(body["errors"][0].get("message"))[:200])
    res = (body.get("data") or {}).get("search") or {}
    cache.put(key, res)
    return res


def _slice(bound: dict) -> tuple[Slice, bool]:
    segs, total, self_transfer = [], 0, False
    for s in bound["segments"]:
        total += int((s.get("duration") or 0) // 60000)
        if s.get("__typename") != "TripSegment":
            self_transfer |= "SELF_TRANSFER" in (s.get("types") or [])
            continue
        carrier = (s.get("marketingCarrier") or {}).get("code") or "??"
        num = str(s.get("flightNumber") or "")
        segs.append(Segment(
            origin=s["origin"]["code"], destination=s["destination"]["code"],
            departure=datetime.fromisoformat(s["departuredAt"]), arrival=datetime.fromisoformat(s["arrivedAt"]),
            carrier=carrier, carrier_name=(s.get("marketingCarrier") or {}).get("name"),
            flight_number=num.removeprefix(carrier) or None,
            duration_min=int(s["duration"] // 60000) if s.get("duration") else None,
        ))
    return Slice(segments=segs, duration_min=max(total, 1)), self_transfer


def parse(res: dict, brand: str) -> list[Itinerary]:
    """SearchOnResultPage payload -> Itineraries (all airports, unfiltered)."""
    name = BRANDS[brand][0]
    out = []
    for f in res.get("flights") or []:
        prices = [((p.get("price") or {}).get("price") or {}) for p in f.get("travelerPrices") or []]
        if not prices or any(p.get("value") is None for p in prices):
            continue
        slices, st = [], "VIRTUAL_INTERLINING" in (f.get("tripCharacteristics") or [])
        for b in f.get("bounds") or []:
            sl, x = _slice(b)
            if not sl.segments:
                break
            slices.append(sl)
            st |= x
        else:
            seats = [d.get("numberOfSeatsLeft") for b in f["bounds"] for s in b["segments"]
                     for d in s.get("segmentDetails") or [] if d.get("numberOfSeatsLeft")]
            warn = [f"Sold by {name} (Etraveli online travel agency), not the airline."]
            if st:
                warn.append(f"Self transfer: {name} combines separate tickets, the connection is not protected "
                            "by the airlines.")
            if seats and min(seats) <= 3:
                warn.append(f"Only {min(seats)} seats left at this {name} price.")
            out.append(Itinerary(
                source=brand, price=round(sum(p["value"] for p in prices) / 100, 2),
                currency=prices[0]["currency"]["code"], slices=slices,
                booking_url=f.get("shareableUrl") or "", seller=name, seller_kind="ota", self_transfer=st,
                warnings=warn,
            ))
    return out


def search_brand(q: SearchQuery, brand: str) -> list[Itinerary]:
    host = domain(brand, q.currency)
    out: dict[str, Itinerary] = {}
    for o in q.origins[:2]:
        for d in q.destinations[:2]:
            if o == d:
                continue
            asks = [(False, 0), (True, 0)] if q.max_stops != 0 else [(True, 0)]
            if q.max_stops != 0:
                asks.append((False, 10))
            for direct, offset in asks:
                res = _post(host, _variables(q, o, d, direct, offset))
                for it in parse(res, brand):
                    ends = [(sl.origin, sl.destination) for sl in it.slices]
                    want = [(o, d)] + ([(d, o)] if q.return_date else [])
                    if ends != want or (q.max_stops is not None and any(s.stops > q.max_stops for s in it.slices)):
                        continue
                    if not it.booking_url:
                        it.booking_url = f"https://{host}{res.get('searchPath') or '/'}"
                    out.setdefault(it.flight_key, it)
    return sorted(out.values(), key=lambda i: i.price)


def search(q: SearchQuery) -> list[Itinerary]:
    return search_brand(q, "gotogate")
