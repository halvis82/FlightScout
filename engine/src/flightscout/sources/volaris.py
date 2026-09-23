"""Volaris (Y4) direct from volaris.com's own backend (Navitaire dotREZ at
apigw.volaris.com). Google Flights has Volaris schedules but no prices for
most of its Mexican routes, so this source fills a real gap.

No key: an anonymous session token comes from GET /api/session. Requests must
look like Chrome at the TLS level (curl_cffi impersonation), otherwise the
Fastly edge answers 406. Prices from the API exclude the TUA airport fee; we
always add it so the price matches the checkout total."""

from __future__ import annotations

import threading
import time
from datetime import date, datetime

from curl_cffi import requests as cr

from .. import airports, cache, fx
from ..models import DatePrice, Itinerary, SearchQuery, Segment, Slice

BASE = "https://apigw.volaris.com/prod"
_HEADERS = {
    "Flow": "MBS", "Frontend": "WEB", "Origin": "https://www.volaris.com",
    "Referer": "https://www.volaris.com/", "Accept": "application/json",
}
_lock = threading.Lock()
_session: cr.Session | None = None
_token: tuple[str, float] | None = None

# Countries Volaris flies in. We only query it when both ends are in this set
# and at least one end is in Mexico (Volaris has no US domestic flights).
COUNTRIES = {"MX", "US", "GT", "SV", "CR", "CO", "PE", "HN"}


def relevant(origins: list[str], destinations: list[str]) -> bool:
    def cc(codes):
        return {a.country for c in codes if (a := airports.get(c))}
    o, d = cc(origins), cc(destinations)
    return bool(o and d and (o | d) <= COUNTRIES and "MX" in (o | d))


def _headers() -> dict:
    global _session, _token
    with _lock:
        if _session is None:
            _session = cr.Session(impersonate="chrome")
        if not _token or time.time() - _token[1] > 10 * 60:
            r = _session.get(f"{BASE}/api/session", headers=_HEADERS, timeout=20)
            r.raise_for_status()
            _token = (r.json()["token"], time.time())
        return {**_HEADERS, "Authorization": _token[0]}


def _post(path: str, body: dict) -> dict:
    h = _headers()
    r = _session.post(f"{BASE}{path}", headers=h, json=body, timeout=30)
    r.raise_for_status()
    return r.json()


def _api_currency(cur: str) -> str:
    return "USD" if cur.upper() == "USD" else "MXN"


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1,
             currency: str = "MXN") -> str:
    q = (f"adt={adults}&chd=0&in1=0&rr={'true' if ret else 'false'}&cc={_api_currency(currency)}"
         f"&dd1={dep.strftime('%m/%d/%Y')}")
    if ret:
        q += f"&dd2={ret.strftime('%m/%d/%Y')}"
    return f"https://www.volaris.com/flight/select?{q}&culture=en-us&o1={origin}&d1={dest}"


def _flights(origin: str, dest: str, day: date, cur: str, adults: int) -> list[dict]:
    key = f"volaris:{origin}:{dest}:{day}:{cur}:{adults}"
    if (hit := cache.get(key)) is not None:
        return hit
    body = {
        "passengers": {"types": [{"type": "ADT", "count": adults}]},
        "criteria": [{"stations": {"originStationCodes": [origin], "destinationStationCodes": [dest]},
                      "dates": {"beginDate": day.strftime("%a, %b %d, %Y")},
                      "filters": {"fareTypes": ["R"], "maxConnections": 20, "bundleControlFilter": 2}}],
        "codes": {"currencyCode": cur, "promotionCode": ""},
        "taxesAndFees": 2, "shouldIncludeSoldOut": True, "shouldIncludeTua": True,
    }
    try:
        d = _post("/api/v3/availability/search", body)
    except Exception as e:
        # Volaris answers 400 for routes it doesn't fly: that's "no flights"
        if getattr(getattr(e, "response", None), "status_code", None) == 400 or "400" in str(e):
            cache.put(key, [])
            return []
        raise
    fares = d.get("faresAvailable") or {}
    out = []
    for res in d.get("results") or []:
        for trip in res.get("trips") or []:
            for journeys in (trip.get("journeysAvailableByMarket") or {}).values():
                for j in journeys:
                    best = None
                    for f in j.get("fares") or []:
                        seats = sum(x.get("availableCount", 0) for x in f.get("details") or [])
                        fa = fares.get(f["fareAvailabilityKey"])
                        if not fa or seats == 0:
                            continue
                        p = fa["totals"]["fareTotal"]
                        if best is None or p < best[0]:
                            best = (p, f.get("tuaAmount") or 0.0, seats)
                    if not best:
                        continue
                    segs = [{
                        "origin": s["designator"]["origin"], "destination": s["designator"]["destination"],
                        "departure": s["designator"]["departure"], "arrival": s["designator"]["arrival"],
                        "carrier": s["identifier"]["carrierCode"], "number": s["identifier"]["identifier"],
                    } for s in j["segments"]]
                    out.append({"segments": segs, "total": best[0] + best[1], "tua": best[1], "seats": best[2]})
    cache.put(key, out)
    return out


def _slice(j: dict) -> Slice:
    segs = [Segment(origin=s["origin"], destination=s["destination"],
                    departure=datetime.fromisoformat(s["departure"]), arrival=datetime.fromisoformat(s["arrival"]),
                    carrier=s["carrier"], carrier_name="Volaris", flight_number=s["number"]) for s in j["segments"]]
    dur = int((segs[-1].arrival - segs[0].departure).total_seconds() // 60)  # local times; approximate
    return Slice(segments=segs, duration_min=max(dur, 1))


def search(q: SearchQuery) -> list[Itinerary]:
    if not relevant(q.origins, q.destinations):
        return []
    cur = _api_currency(q.currency)
    out: list[Itinerary] = []
    for o in q.origins[:3]:
        for d in q.destinations[:3]:
            outs = _flights(o, d, q.departure, cur, q.adults)
            backs = _flights(d, o, q.return_date, cur, q.adults) if q.return_date else [None]
            outs = sorted(outs, key=lambda x: x["total"])[:6]
            backs = sorted(backs, key=lambda x: x["total"])[:6] if q.return_date else [None]
            for a in outs:
                for b in backs:
                    slices = [_slice(a)] + ([_slice(b)] if b else [])
                    total = a["total"] + (b["total"] if b else 0)
                    warn = []
                    if a["seats"] <= 3 or (b and b["seats"] <= 3):
                        warn.append("Only a few seats left at this Volaris fare.")
                    out.append(Itinerary(
                        source="volaris", price=round(total, 2), currency=cur, slices=slices,
                        booking_url=deeplink(o, d, q.departure, q.return_date, q.adults, cur),
                        seller="Volaris", seller_kind="airline", warnings=warn,
                    ))
    return out


def dates(origin: str, dest: str, start: date, end: date, currency: str = "MXN") -> list[DatePrice]:
    """Indicative whole-month low fares (about 5 to 8 percent under the live
    price since the calendar excludes the airport fee)."""
    cur = _api_currency(currency)
    out: list[DatePrice] = []
    month = start.replace(day=1)
    while month <= end:
        key = f"volaris-month:{origin}:{dest}:{month}:{cur}"
        data = cache.get(key, ttl=6 * 3600)
        if data is None:
            body = {"origin": origin, "destination": dest, "date": month.isoformat(), "passengerCount": 1,
                    "currencyCode": cur, "promoCode": "", "shouldIncludeDeparture": True,
                    "shouldIncludeReturn": False, "isVClub": False, "hasMacDepartureStation": False}
            d = _post("/api/v1/lowfare/bymonth", body)
            data = (d["LowfareMonthFirst"]["availabilityLowFare"]["lowFareDateMarkets"]
                    + d["LowfareMonthSecond"]["availabilityLowFare"]["lowFareDateMarkets"])
            cache.put(key, data)
        for m in data:
            day = date.fromisoformat(m["departureDate"][:10])
            a = m.get("lowestFareAmount")
            if not a or not (start <= day <= end):
                continue
            price = a["fareAmount"] + a["taxesAndFeesAmount"]
            if currency.upper() != cur:
                price = fx.convert(price, cur, currency)
            out.append(DatePrice(origin=origin, destination=dest, departure=day, price=round(price, 2),
                                 currency=currency.upper(), source="volaris",
                                 booking_url=deeplink(origin, dest, day, currency=cur)))
        month = (month.replace(day=28) + __import__("datetime").timedelta(days=4)).replace(day=1)
    best: dict[date, DatePrice] = {}
    for x in out:
        if x.departure not in best or x.price < best[x.departure].price:
            best[x.departure] = x
    return sorted(best.values(), key=lambda x: x.departure)
