"""Wego (metasearch, strongest in the Middle East and Asia) through the JSON
API its own website polls (srv.wego.com/v2/metasearch, keyless, Chrome TLS
impersonation, no browser).

One POST starts a live search, then a few GETs poll for fares. ``offset`` is
the number of fares already received, so each poll returns only the new ones;
the search is complete when two polls in a row bring nothing new (15 to 20
seconds). Each fare is one booking site's live price for one trip, all
passengers included. We keep the cheapest live fare per trip and drop
fares Wego marks as cached (``NORMAL_CACHE``: a provider's stored price, not
a live quote).

The market (``siteCode``) sets which booking sites answer: we use the origin
country when Wego runs a site there, else the US site, and ask for prices in
the query currency."""

from __future__ import annotations

import threading
import time
from datetime import date, datetime

from curl_cffi import requests as cr

from .. import airports, cache
from ..models import Itinerary, SearchQuery, Segment, Slice

API = "https://srv.wego.com/v2/metasearch/flights/searches"
SITE = "https://www.wego.com"
_HEADERS = {"Origin": SITE, "Referer": SITE + "/", "Accept": "application/json",
            "Content-Type": "application/json"}
_CABIN = {"economy": "economy", "premium": "premium_economy", "business": "business", "first": "first"}
# Countries with their own Wego site (siteCode). Anything else searches the US site.
SITES = {"AE", "SA", "EG", "KW", "QA", "BH", "OM", "JO", "LB", "MA", "DZ", "TN", "IQ", "IN", "PK", "BD", "LK",
         "SG", "MY", "ID", "TH", "PH", "VN", "HK", "TW", "JP", "KR", "AU", "NZ", "US", "CA", "GB", "DE", "FR",
         "IT", "ES", "NL", "TR", "IR", "NG", "ZA", "KE", "BR", "MX"}
POLLS = 8
_local = threading.local()


def relevant(origins: list[str], destinations: list[str]) -> bool:
    return True  # a metasearch: every market


def _session() -> cr.Session:
    if not hasattr(_local, "s"):
        _local.s = cr.Session(impersonate="chrome")
    return _local.s


def site_code(origin: str) -> str:
    ap = airports.get(origin)
    return ap.country if ap and ap.country in SITES else "US"


def search_url(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1,
               cabin: str = "economy") -> str:
    legs = f"c{origin}-c{dest}-{dep.isoformat()}" + (f":c{dest}-c{origin}-{ret.isoformat()}" if ret else "")
    return f"{SITE}/flights/searches/{legs}/{_CABIN.get(cabin, 'economy')}/{adults}a:0c:0i?sort=price&order=asc"


def _body(o: str, d: str, dep: date, ret: date | None, adults: int, cabin: str, currency: str) -> dict:
    legs = [{"departureAirportCode": o, "arrivalAirportCode": d, "outboundDate": dep.isoformat()}]
    if ret:
        legs.append({"departureAirportCode": d, "arrivalAirportCode": o, "outboundDate": ret.isoformat()})
    return {"search": {"cabin": _CABIN.get(cabin, "economy"), "deviceType": "DESKTOP", "appType": "WEB_APP",
                       "userLoggedIn": False, "adultsCount": adults, "childrenCount": 0, "infantsCount": 0,
                       "siteCode": site_code(o), "currencyCode": currency.upper(), "locale": "en", "legs": legs},
            "offset": 0, "paymentMethodIds": [], "providerTypes": [], "airlines": [], "alliances": [],
            "stopoverAirports": [], "stopoverDurations": [], "stops": [], "departureTimeBuckets": []}


def _fetch(o: str, d: str, dep: date, ret: date | None, adults: int, cabin: str, currency: str) -> dict:
    """Run one live search to completion. Returns {"fares", "trips", "legs",
    "providers"} merged over every poll."""
    s = _session()
    r = s.post(API, json=_body(o, d, dep, ret, adults, cabin, currency), headers=_HEADERS, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"wego: search start HTTP {r.status_code}")
    sid = r.json()["search"]["id"]
    acc: dict[str, dict] = {"fares": {}, "trips": {}, "legs": {}, "providers": {}, "airlines": {}}
    empty = 0
    for i in range(POLLS):
        time.sleep(2.5 if i else 4)
        r = s.get(f"{API}/{sid}/results", headers=_HEADERS, timeout=60,
                  params={"offset": len(acc["fares"]), "locale": "en", "currencyCode": currency.upper(),
                          "paymentMethodIds": ""})
        if r.status_code != 200:
            raise RuntimeError(f"wego: results HTTP {r.status_code}")
        page = r.json()
        new = page.get("fares") or []
        for k in acc:
            for x in page.get(k) or []:
                acc[k][x.get("id") or x.get("code")] = x
        empty = 0 if new else empty + 1
        if acc["fares"] and empty >= 2 and i >= 3:
            break
    return {k: list(v.values()) for k, v in acc.items()}


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s[:19])


def _slice(leg: dict, names: dict[str, str]) -> Slice:
    segs = []
    for s in leg["segments"]:
        code = s.get("airlineCode") or s["designatorCode"][:2]
        segs.append(Segment(
            origin=s["departureAirportCode"], destination=s["arrivalAirportCode"],
            departure=_dt(s["departureDateTime"]), arrival=_dt(s["arrivalDateTime"]),
            carrier=code, carrier_name=names.get(code),
            flight_number=s["designatorCode"].removeprefix(code) or None,
            duration_min=s.get("durationMinutes"), aircraft=s.get("aircraftCode"),
        ))
    return Slice(segments=segs, duration_min=max(1, int(leg.get("durationMinutes") or 1)))


def parse(data: dict, q: SearchQuery, currency: str, url: str, limit: int = 60) -> list[Itinerary]:
    """Merged poll data -> one Itinerary per trip at its cheapest live fare."""
    legs = {x["id"]: x for x in data.get("legs") or []}
    trips = {x["id"]: x for x in data.get("trips") or []}
    provs = {x["code"]: x for x in data.get("providers") or []}
    names = {a["code"]: a.get("name") for a in data.get("airlines") or [] if a.get("code")}
    best: dict[str, dict] = {}
    for f in data.get("fares") or []:
        if any("CACHE" in t for t in f.get("legsSourceTypes") or []):
            continue  # a provider's stored price, not a live quote
        price = (f.get("price") or {}).get("totalAmount")
        if not price or f.get("tripId") not in trips:
            continue
        if f["tripId"] not in best or price < best[f["tripId"]]["price"]["totalAmount"]:
            best[f["tripId"]] = f
    out: list[Itinerary] = []
    for tid, f in sorted(best.items(), key=lambda kv: kv[1]["price"]["totalAmount"]):
        tl = [legs.get(x) for x in trips[tid].get("legIds") or []]
        if not tl or any(x is None or not x.get("segments") for x in tl):
            continue
        slices = [_slice(x, names) for x in tl]
        if slices[0].origin not in q.origins or slices[0].destination not in q.destinations:
            continue  # Wego searches cities: keep the airports asked for
        if q.max_stops is not None and any(s.stops > q.max_stops for s in slices):
            continue
        p = provs.get(f.get("providerCode")) or {}
        kind = "airline" if p.get("type") == "airline" else "ota"
        seller = p.get("name") or f.get("providerCode")
        out.append(Itinerary(
            source="wego", price=round(float(f["price"]["totalAmount"]), 2),
            currency=(f["price"].get("currencyCode") or currency).upper(), slices=slices, booking_url=url,
            seller=seller, seller_kind=kind,
            warnings=[] if kind == "airline" else [f"Sold by {seller} (online travel agency) via Wego."],
        ))
        if len(out) >= limit:
            break
    return out


def search(q: SearchQuery) -> list[Itinerary]:
    cur = q.currency.upper()
    out: list[Itinerary] = []
    for o in q.origins[:2]:
        for d in q.destinations[:2]:
            if o == d:
                continue
            key = f"wego:{o}:{d}:{q.departure}:{q.return_date}:{q.adults}:{q.cabin}:{cur}"
            if (data := cache.get(key, ttl=1800)) is None:
                data = _fetch(o, d, q.departure, q.return_date, q.adults, q.cabin, cur)
                if data["fares"]:
                    cache.put(key, data)
            out += parse(data, q, cur, search_url(o, d, q.departure, q.return_date, q.adults, q.cabin))
    return out
