"""Sky Airline (H2) direct from skyairline.com's own booking backend
(api.skyairline.com, an Azure APIM gateway in front of their Sabre based
shopping). Google Flights has Sky schedules but no prices, so this source
fills a real gap for Chile and Peru domestic and regional routes.

No login: the APIM subscription keys are public constants shipped in the
initial-sale web app. Cloudflare sits in front but lets plain TLS clients
through; we still impersonate Chrome to match the site. Prices from
farequoting are fare plus taxes, which equals the checkout "Total a pagar"
(verified in a browser: SCL-ANF 2026-11-19 Basic, CLP 32,024 both places)."""

from __future__ import annotations

import os

import threading
import time
from datetime import date, datetime, timedelta

from curl_cffi import requests as cr

from .. import airports, cache, fx
from ..models import DatePrice, Itinerary, SearchQuery, Segment, Slice

API = "https://api.skyairline.com"
# Sky's web app ships its API gateway keys to every visitor (see
# initial-sale.skyairline.com in browser dev tools). They are not kept in this
# public repo: set FLIGHTSCOUT_SKY_KEYS="<shopping key>,<routes key>" to enable
# this source. Without it the source stays off.
_KEYS = [k.strip() for k in os.environ.get("FLIGHTSCOUT_SKY_KEYS", "").split(",") if k.strip()]
_KEY_SHOP = _KEYS[0] if _KEYS else ""
_KEY_ROUTES = _KEYS[1] if len(_KEYS) > 1 else _KEY_SHOP
_BASE_HEADERS = {
    "channel": "WEB", "Accept": "application/json",
    "Origin": "https://initial-sale.skyairline.com", "Referer": "https://initial-sale.skyairline.com/",
}
# Point of sale (home market) -> path segment used by the booking site.
MARKETS = {"CL": "chile", "PE": "peru", "AR": "argentina", "BR": "brasil", "UY": "uruguay", "US": "unitedstates"}
# Currency the lowest fares calendar wants per market (it accepts only CLP,
# USD, ARS and BRL, and AR must be ARS).
_CAL_CUR = {"CL": "CLP", "PE": "USD", "AR": "ARS", "BR": "BRL", "UY": "USD", "US": "USD"}
# Countries in Sky's network (aeropathways, Sept 2026). Every route touches
# Chile or Peru.
COUNTRIES = {"CL", "PE", "AR", "BR", "UY", "DO", "US", "MX", "CO", "AW"}

_lock = threading.Lock()
_session: cr.Session | None = None
_last_call = 0.0
_MIN_GAP = 0.4  # seconds between calls, be polite


def _cc(code: str) -> str | None:
    a = airports.get(code)
    return a.country if a else None


def relevant(origins: list[str], destinations: list[str]) -> bool:
    if not _KEY_SHOP:
        return False
    return _relevant(origins, destinations)


def _relevant(origins: list[str], destinations: list[str]) -> bool:
    o = {c for x in origins if (c := _cc(x))}
    d = {c for x in destinations if (c := _cc(x))}
    return bool(o and d and (o | d) <= COUNTRIES and ({"CL", "PE"} & (o | d)))


def _request(method: str, path: str, key: str, market: str = "CL", body: dict | None = None) -> dict:
    global _session, _last_call
    with _lock:
        if _session is None:
            _session = cr.Session(impersonate="chrome")
        wait = _MIN_GAP - (time.time() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.time()
    h = {**_BASE_HEADERS, "ocp-apim-subscription-key": key, "homemarket": market, "pointofsale": market}
    # The gateway occasionally stalls or answers a stray 400 to a request that
    # succeeds on repeat, so retry once.
    for attempt in range(2):
        try:
            r = _session.request(method, f"{API}{path}", headers=h, json=body, timeout=25)
            if r.status_code != 200 and r.status_code != 404 and attempt == 0:
                time.sleep(1)
                continue
            r.raise_for_status()
            return r.json()
        except cr.exceptions.Timeout:
            if attempt:
                raise
    raise RuntimeError("skyairline: no response")


def _routes() -> dict[str, set[str]]:
    """Origin -> destinations Sky sells (includes connections)."""
    hit = cache.get("sky:routes", ttl=24 * 3600)
    if hit is None:
        d = _request("GET", "/aeropath/v1/getRoutesList", _KEY_ROUTES)
        hit = {r["origin"]: r["destinations"] for r in d.get("routes") or []}
        cache.put("sky:routes", hit)
    return {k: set(v) for k, v in hit.items()}


def _market(origin: str) -> str:
    c = _cc(origin)
    return c if c in MARKETS else "CL"


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1,
             market: str = "CL") -> str:
    q = f"origin={origin}&destination={dest}&departureDate={dep.isoformat()}"
    if ret:
        q += f"&arrivalDate={ret.isoformat()}&flightType=RT"
    else:
        q += "&flightType=OW"
    return (f"https://initial-sale.skyairline.com/en/{MARKETS.get(market, 'chile')}?{q}"
            f"&ADT={adults}&CHD=0&INF=0&PET=0")


def _flights(origin: str, dest: str, day: date, adults: int, market: str) -> list[dict]:
    key = f"sky:{origin}:{dest}:{day}:{adults}:{market}"
    if (hit := cache.get(key)) is not None:
        return hit
    body = {
        "cabinClass": "Economy", "currency": None, "awardBooking": False, "pointOfSale": market,
        "searchType": "BRANDED",
        "itineraryParts": [{"origin": {"code": origin, "useNearbyLocations": False},
                            "destination": {"code": dest, "useNearbyLocations": False},
                            "departureDate": {"date": day.isoformat()},
                            "selectedOfferRef": None, "plusMinusDays": None}],
        "passengers": {"ADT": adults, "CHD": 0, "INF": 0, "PET": 0},
        "trendIndicator": None, "preferredOperatingCarrier": None,
    }
    d = _request("POST", "/farequoting/v1/search/flight?stage=IS", _KEY_SHOP, market, body)
    out = []
    for part in d.get("itineraryParts") or []:
        for it in part:
            fares = [f for f in it.get("fares") or [] if f.get("status") and (f.get("total") or {}).get("amount")]
            if not fares:
                continue
            best = min(fares, key=lambda f: f["total"]["amount"])
            segs = [{
                "origin": s["origin"], "destination": s["destination"],
                "departure": s["departure"], "arrival": s["arrival"],
                "dep_off": s.get("departureGMTOffset"), "arr_off": s.get("arrivalGMTOffset"),
                "carrier": s["flight"].get("airlineCode") or "H2",
                "number": str(s["flight"]["flightNumber"]), "duration": s.get("duration"),
                "aircraft": s.get("equipment"),
            } for s in it["segments"]]
            out.append({"segments": segs, "total": float(best["total"]["amount"]),
                        "currency": best["total"]["currency"], "brand": best.get("brandId"),
                        "duration": it.get("totalDuration")})
    cache.put(key, out)
    return out


def _slice(j: dict) -> Slice:
    segs = [Segment(origin=s["origin"], destination=s["destination"],
                    departure=datetime.fromisoformat(s["departure"]), arrival=datetime.fromisoformat(s["arrival"]),
                    carrier=s["carrier"], carrier_name="Sky Airline" if s["carrier"] == "H2" else None, flight_number=s["number"],
                    duration_min=s.get("duration"), aircraft=s.get("aircraft")) for s in j["segments"]]
    dur = j.get("duration") or int((segs[-1].arrival - segs[0].departure).total_seconds() // 60)
    return Slice(segments=segs, duration_min=max(int(dur), 1))


def search(q: SearchQuery) -> list[Itinerary]:
    if not relevant(q.origins, q.destinations):
        return []
    routes = _routes()
    out: list[Itinerary] = []
    for o in q.origins[:3]:
        for d in q.destinations[:3]:
            if d not in routes.get(o, ()):
                continue
            market = _market(o)
            outs = sorted(_flights(o, d, q.departure, q.adults, market), key=lambda x: x["total"])[:6]
            backs = [None]
            if q.return_date:
                backs = sorted(_flights(d, o, q.return_date, q.adults, market), key=lambda x: x["total"])[:6]
            for a in outs:
                if q.max_stops is not None and len(a["segments"]) - 1 > q.max_stops:
                    continue
                for b in backs:
                    if b and q.max_stops is not None and len(b["segments"]) - 1 > q.max_stops:
                        continue
                    if b and b["currency"] != a["currency"]:
                        continue
                    slices = [_slice(a)] + ([_slice(b)] if b else [])
                    total = a["total"] + (b["total"] if b else 0)
                    out.append(Itinerary(
                        source="skyairline", price=round(total, 2), currency=a["currency"], slices=slices,
                        booking_url=deeplink(o, d, q.departure, q.return_date, q.adults, market),
                        seller="Sky Airline", seller_kind="airline",
                        warnings=["Sky Basic fare: personal item only, cabin bag costs extra."],
                    ))
    return out


def dates(origin: str, dest: str, start: date, end: date, currency: str = "USD") -> list[DatePrice]:
    """Cheapest one way fare (taxes included) per day, from the calendar the
    booking site shows. One call covers about four weeks. The calendar
    service is flaky: at times it marks every day unavailable (the site's
    own date strip then shows "-"), in which case this returns nothing."""
    market = _market(origin)
    out: dict[date, DatePrice] = {}
    center = start + timedelta(days=14)
    while center - timedelta(days=14) <= end:
        key = f"sky-lowest:{origin}:{dest}:{center}:{market}"
        data = cache.get(key, ttl=6 * 3600)
        if data is None:
            body = {"currency": _CAL_CUR.get(market, "USD"),
                    "passengerCount": [{"ptc": "ADT", "quantity": 1}, {"ptc": "CHD", "quantity": 0},
                                       {"ptc": "INF", "quantity": 0}],
                    "itineraryParts": [{"origin": origin, "destination": dest, "departureDate": center.isoformat(),
                                        "dateFlexibility": 14}],
                    "goingFaresFetched": []}
            d = _request("POST", "/shopping-lowest-fares/lowest-fares/v1/search", _KEY_SHOP, market, body)
            data = {"currency": d.get("currency"), "parts": d.get("itineraryParts") or []}
            cache.put(key, data)
        cur = data["currency"] or "CLP"
        for p in data["parts"]:
            day = date.fromisoformat(p["departureDate"][:10])
            price = (p.get("pricingInfo") or {}).get("baseFareWithTaxes")
            if not p.get("isAvailable") or not price or not (start <= day <= end):
                continue
            if currency.upper() != cur.upper():
                price = fx.convert(price, cur, currency)
            dp = DatePrice(origin=origin, destination=dest, departure=day, price=round(price, 2),
                           currency=currency.upper(), source="skyairline",
                           booking_url=deeplink(origin, dest, day, market=market))
            if day not in out or dp.price < out[day].price:
                out[day] = dp
        center += timedelta(days=29)
    return sorted(out.values(), key=lambda x: x.departure)
