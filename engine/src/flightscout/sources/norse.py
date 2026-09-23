"""Norse Atlantic Airways direct from flynorse.com's own backend (Navitaire
dotREZ behind services.flynorse.com). Norse flies as N0 (Norway) and Z0 (UK,
all Gatwick flights). Google Flights prices Norse correctly (LGW-MCO $548,
ARN-BKK $620 in the September 2026 audit, same as here) but Kiwi does not
sell it at all, so this adds the airline direct offer and a fare calendar.

No key: an anonymous token comes from POST /api/v1/token. Requests need
Chrome level TLS (curl_cffi impersonation). ``fareTotal`` is per passenger
and already includes taxes and carrier fees, so it is the checkout price of
the fare before optional extras."""

from __future__ import annotations

import threading
import time
from datetime import date, datetime, timedelta

from curl_cffi import requests as cr

from .. import cache, fx
from ..models import DatePrice, Itinerary, SearchQuery, Segment, Slice

BASE = "https://services.flynorse.com/api"
_HEADERS = {
    "x-app-name": "norse-ui", "x-app-version": "v20.10.2.62", "Origin": "https://flynorse.com",
    "Referer": "https://flynorse.com/", "Accept": "application/json",
}
_lock = threading.Lock()
_session: cr.Session | None = None
_token: tuple[str, float] | None = None

# Norse's own stations (checked 2026-09-22 via /v1/stations/active/withmarkets).
# The live route list is fetched and cached in _markets(); this static set
# only keeps relevant() free of network calls.
AIRPORTS = {"LGW", "JFK", "MCO", "BKK", "HKT", "CPT", "ATH", "FCO", "OSL", "ARN", "MAN"}
CURRENCIES = {"USD", "EUR", "GBP", "NOK", "SEK", "ZAR"}
_CABIN = {"economy": "Economy", "premium": "Premium", "business": "Premium"}


def relevant(origins: list[str], destinations: list[str]) -> bool:
    return bool(set(origins) & AIRPORTS and set(destinations) & AIRPORTS)


def _headers() -> dict:
    global _session, _token
    with _lock:
        if _session is None:
            _session = cr.Session(impersonate="chrome")
        # tokens idle out after 15 minutes
        if not _token or time.time() - _token[1] > 10 * 60:
            r = _session.post(f"{BASE}/v1/token?cookie=false", json={"platformType": "Web"},
                              headers=_HEADERS, timeout=30)
            r.raise_for_status()
            _token = (r.json()["data"]["token"], time.time())
        return {**_HEADERS, "Authorization": f"Bearer {_token[0]}"}


def _req(method: str, path: str, body: dict | None = None) -> dict:
    h = _headers()
    r = _session.request(method, f"{BASE}{path}", headers=h, json=body, timeout=45)
    r.raise_for_status()
    d = r.json()
    if d.get("errors"):
        raise RuntimeError(f"norse: {d['errors']}"[:300])
    return d.get("data")


def _markets() -> dict[str, set[str]]:
    key = "norse-markets"
    data = cache.get(key, ttl=24 * 3600)
    if data is None:
        data = {s["stationCode"]: [m["stationCode"] for m in s.get("validMarkets") or [] if not m.get("isDohop")]
                for s in _req("GET", "/v1/stations/active/withmarkets") or [] if s.get("isNorse")}
        cache.put(key, data)
    return {k: set(v) for k, v in data.items()}


def _api_currency(cur: str) -> str:
    return cur.upper() if cur.upper() in CURRENCIES else "USD"


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1,
             currency: str = "USD") -> str:
    """Norse's availability page. Parameter names come from the site bundle's
    own search URL builder (origins, destinations, departureDate, returnDate,
    adult as a comma list of ages). The route is confirmed to load the
    availability view; the prefilled results could not be screenshotted
    because Cloudflare challenges headless browsers on flynorse.com."""
    u = (f"https://flynorse.com/en-us/booking/availability?origins={origin}&destinations={dest}"
         f"&departureDate={dep.isoformat()}&adult={','.join(['18'] * adults)}&currency={_api_currency(currency)}")
    if ret:
        u += f"&returnDate={ret.isoformat()}"
    return u


def _search(origin: str, dest: str, dep: date, ret: date | None, cur: str, adults: int,
            cabin: str) -> list[list[dict]]:
    """One list of journeys per direction, each journey with its cheapest fare
    in the requested cabin (per passenger)."""
    key = f"norse:{origin}:{dest}:{dep}:{ret}:{cur}:{adults}:{cabin}"
    if (hit := cache.get(key)) is not None:
        return hit
    crit = [{"origin": origin, "destination": dest, "beginDate": dep.isoformat()}]
    if ret:
        crit.append({"origin": dest, "destination": origin, "beginDate": ret.isoformat()})
    body = {"childDobs": [], "infantDobs": [], "criteria": crit,
            "passengers": [{"type": "ADT", "count": adults}], "currencyCode": cur,
            "promotionCode": "", "clearBooking": True, "isSeatsBeforeBags": False}
    data = _req("POST", "/v1/availability/search?clear=true", body) or {}
    out: list[list[dict]] = []
    for res in data.get("results") or []:
        for trip in res.get("trips") or []:
            journeys = []
            for j in trip.get("journeysAvailableByMarket") or []:
                fares = [f["details"] for f in j.get("fares") or []
                         if f["details"].get("cabin") == cabin and f["details"].get("availableCount", 0) > 0]
                if not fares:
                    continue
                best = min(fares, key=lambda f: f["totals"]["fareTotal"])
                segs = []
                for s in j["segments"]:
                    for leg in s.get("legs") or [s]:
                        segs.append({
                            "origin": leg["designator"]["origin"], "destination": leg["designator"]["destination"],
                            "departure": leg["designator"]["departure"], "arrival": leg["designator"]["arrival"],
                            "carrier": s["identifier"]["carrierCode"], "number": s["identifier"]["identifier"],
                            "aircraft": leg.get("equipmentType"),
                        })
                journeys.append({"segments": segs, "fare": best["totals"]["fareTotal"],
                                 "bundle": best.get("bundleCode"), "seats": best.get("availableCount", 0),
                                 "minutes": (j.get("totalTravelTime") or 0) // 60000})
            out.append(journeys)
    cache.put(key, out)
    return out


def _slice(j: dict) -> Slice:
    segs = [Segment(origin=s["origin"], destination=s["destination"],
                    departure=datetime.fromisoformat(s["departure"]), arrival=datetime.fromisoformat(s["arrival"]),
                    carrier=s["carrier"], carrier_name="Norse Atlantic Airways", flight_number=s["number"],
                    aircraft=s.get("aircraft")) for s in j["segments"]]
    return Slice(segments=segs, duration_min=max(j["minutes"], 1))


def search(q: SearchQuery) -> list[Itinerary]:
    if not relevant(q.origins, q.destinations) or q.cabin not in _CABIN:
        return []
    markets = _markets()
    cur = _api_currency(q.currency)
    out: list[Itinerary] = []
    for o in q.origins[:3]:
        for d in q.destinations[:3]:
            if d not in markets.get(o, set()):
                continue
            dirs = _search(o, d, q.departure, q.return_date, cur, q.adults, _CABIN[q.cabin])
            if not dirs or not dirs[0] or (q.return_date and (len(dirs) < 2 or not dirs[1])):
                continue
            outs = sorted(dirs[0], key=lambda x: x["fare"])[:6]
            backs = sorted(dirs[1], key=lambda x: x["fare"])[:6] if q.return_date else [None]
            for a in outs:
                for b in backs:
                    if q.max_stops is not None and (len(a["segments"]) - 1 > q.max_stops
                                                    or (b and len(b["segments"]) - 1 > q.max_stops)):
                        continue
                    per_pax = a["fare"] + (b["fare"] if b else 0)
                    warn = []
                    if a["seats"] <= 3 or (b and b["seats"] <= 3):
                        warn.append("Only a few seats left at this Norse fare.")
                    if a["bundle"] == "EL" or (b and b["bundle"] == "EL"):
                        warn.append("Norse Light fare: no checked bag and no online check in.")
                    out.append(Itinerary(
                        source="norse", price=round(per_pax * q.adults, 2), currency=cur,
                        slices=[_slice(a)] + ([_slice(b)] if b else []),
                        booking_url=deeplink(o, d, q.departure, q.return_date, q.adults, cur),
                        seller="Norse Atlantic Airways", seller_kind="airline", warnings=warn,
                    ))
    return out


def dates(origin: str, dest: str, start: date, end: date, currency: str = "USD",
          cabin: str = "economy") -> list[DatePrice]:
    """Cheapest one way fare per day from Norse's low fare calendar (the same
    all in fareTotal the booking page shows)."""
    cur = _api_currency(currency)
    want = _CABIN.get(cabin, "Economy")
    out: list[DatePrice] = []
    month = start.replace(day=1)
    while month <= end:
        last = (month.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        key = f"norse-month:{origin}:{dest}:{month}:{cur}"
        data = cache.get(key, ttl=6 * 3600)
        if data is None:
            body = {"childDobs": [], "infantDobs": [],
                    "criteria": [{"origin": origin, "destination": dest, "beginDate": month.isoformat(),
                                  "endDate": last.isoformat()}],
                    "passengers": [{"type": "ADT", "count": 1}], "currencyCode": cur, "promotionCode": "",
                    "clearBooking": True, "isSeatsBeforeBags": False}
            data = _req("POST", "/v1/availability/lowfare?includePremium=true", body) or []
            cache.put(key, data)
        for pair in data:
            for c in pair.get("cabins") or []:
                if c.get("cabinName") != want:
                    continue
                for x in c.get("lowFareAmounts") or []:
                    day = date.fromisoformat(x["departureDate"][:10])
                    if not x.get("fareTotal") or not (start <= day <= end):
                        continue
                    price = x["fareTotal"]
                    if currency.upper() != cur:
                        price = fx.convert(price, cur, currency)
                    out.append(DatePrice(origin=origin, destination=dest, departure=day, price=round(price, 2),
                                         currency=currency.upper(), source="norse",
                                         booking_url=deeplink(origin, dest, day, currency=cur)))
        month = last + timedelta(days=1)
    return sorted(out, key=lambda x: x.departure)
