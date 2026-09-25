"""Biman Bangladesh Airlines (BG) direct from booking.biman-airlines.com.
Bangladesh's flag carrier (Dhaka hub: Gulf, India, South East Asia, London,
Manchester, Rome, Toronto, Tokyo), thinly covered by Kiwi and the OTAs.

Plain HTTP: the booking app is Sabre Digital Experience (DX), whose own page
posts the ``bookingAirSearch`` GraphQL query to ``/api/graphql`` with the
public ``x-sabre-storefront: BGDX`` header (no key, no session). The HTML
pages sit behind Imperva, the API does not (for now).

The answer is Sabre's shopping JSON with Jackson object references: every
itinerary part is written out once (``"@id"``) and referenced elsewhere
(``{"@ref": "7"}``). ``brandedResults.itineraryPartBrands[i]`` lists the
flights of bound ``i`` with each fare brand's ``total`` (incl. taxes) per
passenger, exactly the "From ... BDT" the flight selection page shows. A
round trip is one request with two parts; the page's trip total is
(outbound + return) x adults, which is what we return. Prices are in the
point of sale's currency (BDT)."""

from __future__ import annotations

import threading
from datetime import date

from curl_cffi import requests as cr

from .. import airports, cache
from ..models import Itinerary, SearchQuery
from ._airline import combine, countries

SITE = "https://booking.biman-airlines.com"
API = f"{SITE}/api/graphql"
NAMES = {"BG": "Biman Bangladesh Airlines"}
_H = {"Accept": "application/json", "Content-Type": "application/json", "x-sabre-storefront": "BGDX",
      "Origin": SITE, "Referer": f"{SITE}/dx/BGDX/"}
_QUERY = ("query bookingAirSearch($airSearchInput: CustomAirSearchInput) {"
          " bookingAirSearch(airSearchInput: $airSearchInput) { originalResponse __typename } }")
_CABIN = {"economy": "Economy", "business": "Business", "first": "Business"}
# Airports on Biman's own network (the booking app's routes.json, 2026-09).
NETWORK = {"AUH", "BKK", "BZL", "CAN", "CCU", "CGP", "CXB", "DAC", "DEL", "DMM", "DOH", "DXB", "FCO", "JED",
           "JFK", "JSR", "KHI", "KTM", "KUL", "KWI", "LHR", "MAA", "MAN", "MCT", "MED", "NRT", "RGN", "RJH",
           "RUH", "SHJ", "SIN", "SPD", "YYZ", "ZYL"}
_DETOUR = 1.6
_lock = threading.Lock()
_session: cr.Session | None = None


def _s() -> cr.Session:
    global _session
    with _lock:
        if _session is None:
            _session = cr.Session(impersonate="chrome")
        return _session


def _ok(o: str, d: str) -> bool:
    if o == d or o not in NETWORK or d not in NETWORK:
        return False
    if "BD" in countries([o]) or "BD" in countries([d]):
        return True
    try:  # abroad to abroad only through Dhaka when that is on the way
        direct = airports.haversine_km(o, d)
        return direct > 0 and (airports.haversine_km(o, "DAC") + airports.haversine_km("DAC", d)) / direct <= _DETOUR
    except Exception:
        return False


def relevant(origins: list[str], destinations: list[str]) -> bool:
    return any(_ok(o, d) for o in origins for d in destinations)


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1,
             cabin: str = "economy") -> str:
    u = (f"{SITE}/dx/BGDX/#/flight-selection?journeyType={'round-trip' if ret else 'one-way'}&locale=en-US"
         f"&awardBooking=false&searchType=BRANDED&cabinClass={_CABIN.get(cabin, 'Economy')}&ADT={adults}"
         f"&CHD=0&INF=0&origin={origin}&destination={dest}&date={dep:%m-%d-%Y}")
    if ret:
        u += f"&origin1={dest}&destination1={origin}&date1={ret:%m-%d-%Y}"
    return u + "&direction=0&pointOfSale=BD"


def _refs(data) -> dict:
    ids: dict = {}

    def walk(x):
        if isinstance(x, dict):
            if "@id" in x:
                ids[x["@id"]] = x
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(data)
    return ids


def _amount(m: dict | None) -> tuple[float, str] | None:
    alts = (m or {}).get("alternatives") or []
    if alts and alts[0]:
        return float(alts[0][0]["amount"]), alts[0][0]["currency"]
    return None


def parse(data: dict, adults: int = 1, cabin: str = "economy") -> tuple[list[list[dict]], str | None]:
    """GraphQL answer -> ([journeys per bound], currency). Each journey keeps
    its cheapest open brand in the cabin, priced for all passengers."""
    res = (((data.get("data") or {}).get("bookingAirSearch") or {}).get("originalResponse")) or data
    want = _CABIN.get(cabin, "Economy")
    ids = _refs(res)
    bounds, currency = [], res.get("currency")
    for part in ((res.get("brandedResults") or {}).get("itineraryPartBrands")) or []:
        js = []
        for ip in part:
            offers = [(a, b) for b in ip.get("brandOffers") or [] if not b.get("soldout")
                      and b.get("cabinClass") == want and (a := _amount(b.get("total")))]
            if not offers:
                continue
            (price, cur), best = min(offers, key=lambda x: x[0][0])
            currency = cur or currency
            it = ip.get("itineraryPart") or {}
            it = ids.get(it.get("@ref"), it)
            segs = []
            for s in it.get("segments") or []:
                s = ids.get(s.get("@ref"), s) if "@ref" in s else s
                f = s.get("flight") or {}
                segs.append({"origin": s["origin"], "destination": s["destination"],
                             "departure": s["departure"] + (s.get("departureGMTOffset") or ""),
                             "arrival": s["arrival"] + (s.get("arrivalGMTOffset") or ""),
                             "carrier": f.get("operatingAirlineCode") or f.get("airlineCode"),
                             "number": str(f.get("flightNumber")), "duration": s.get("duration"),
                             "aircraft": s.get("equipment")})
            if segs:
                js.append({"segments": segs, "total": round(price * adults, 2), "fare": best.get("brandId"),
                           "seats": (best.get("seatsRemaining") or {}).get("count"),
                           "duration": it.get("totalDuration") or ip.get("duration")})
        bounds.append(js)
    return bounds, currency


def _fetch(o: str, d: str, dep: date, ret: date | None, adults: int, cabin: str) -> dict:
    key = f"biman:{o}:{d}:{dep}:{ret}:{adults}:{cabin}"
    if (hit := cache.get(key)) is not None:
        return hit

    def part(a, b, day):
        return {"from": {"useNearbyLocations": False, "code": a}, "to": {"useNearbyLocations": False, "code": b},
                "when": {"date": day.isoformat()}}

    parts = [part(o, d, dep)] + ([part(d, o, ret)] if ret else [])
    body = {"operationName": "bookingAirSearch", "query": _QUERY, "variables": {"airSearchInput": {
        "cabinClass": _CABIN.get(cabin, "Economy"), "awardBooking": False, "promoCodes": [], "searchType": "BRANDED",
        "itineraryParts": parts, "passengers": {"ADT": adults}, "pointOfSale": "BD"}}}
    r = _s().post(API, json=body, headers=_H, timeout=45)
    r.raise_for_status()
    data = r.json()
    if not (((data.get("data") or {}).get("bookingAirSearch") or {}).get("originalResponse")):
        raise RuntimeError(f"biman: unexpected response {r.text[:150]!r}")
    cache.put(key, data)
    return data


def search(q: SearchQuery) -> list[Itinerary]:
    if q.cabin not in _CABIN:
        return []
    out: list[Itinerary] = []
    pairs = [(o, d) for o in q.origins[:3] for d in q.destinations[:3] if _ok(o, d)]
    for o, d in pairs[:3]:
        bounds, cur = parse(_fetch(o, d, q.departure, q.return_date, q.adults, q.cabin), q.adults, q.cabin)
        outs = bounds[0] if bounds else []
        backs = (bounds[1] if len(bounds) > 1 else []) if q.return_date else None
        if not outs or (q.return_date and not backs):
            continue
        out += combine(q, "biman", "Biman Bangladesh Airlines", outs, backs, cur or "BDT",
                       deeplink(o, d, q.departure, q.return_date, q.adults, q.cabin), NAMES,
                       note="Biman cheapest fare brand in the cabin.")
    return out
