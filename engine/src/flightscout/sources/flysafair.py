"""FlySafair (FA) direct from flysafair.co.za. South Africa's largest low cost
carrier (domestic trunk routes plus a few regional ones). Kiwi and Google
often show only part of its schedule or stale prices.

Plain HTTP: the site is a Vue app on Sabre's ezyCommerce platform. Its own
page config (``window.runtimeConfig`` in the home page HTML) carries the API
hosts and the public ``Tenant-Identifier`` key every visitor's browser sends;
we read it at runtime (cached a day). ``Availability/SearchShop`` is the call
the flight selection page makes. For each flight ``lowestPriceTotal`` is the
cheapest open fare ("Low") for all passengers incl. taxes and fuel surcharge,
which is what the page lists per person as "From R ...".

Round trips are one call with two routes; FlySafair prices each direction on
its own. Prices are in ZAR."""

from __future__ import annotations

import json
import re
import threading
from datetime import date

from curl_cffi import requests as cr

from .. import cache
from ..models import Itinerary, SearchQuery
from ._airline import combine

SITE = "https://www.flysafair.co.za"
NAMES = {"FA": "FlySafair"}
_lock = threading.Lock()
_session: cr.Session | None = None


def _s() -> cr.Session:
    global _session
    with _lock:
        if _session is None:
            _session = cr.Session(impersonate="chrome")
        return _session


def _config() -> dict:
    cfg = cache.get("flysafair:config", ttl=24 * 3600)
    if cfg:
        return cfg
    html = _s().get(f"{SITE}/", timeout=30).text
    m = re.search(r"window\.runtimeConfig\s*=\s*(\{.*?\})\s*</script>", html, re.S)
    if not m:
        raise RuntimeError("flysafair: no runtimeConfig on the home page")
    full = json.loads(m.group(1))
    cfg = {k: full[k] for k in ("apiHost", "gcpApiHost", "apiKey") if full.get(k)}
    if "apiKey" not in cfg or "apiHost" not in cfg:
        raise RuntimeError("flysafair: runtimeConfig without API host or key")
    cache.put("flysafair:config", cfg)
    return cfg


def _headers(cfg: dict) -> dict:
    return {"Tenant-Identifier": cfg["apiKey"], "Channel": "web", "Accept": "text/plain",
            "Content-Type": "application/json", "Origin": SITE, "Referer": f"{SITE}/"}


def network() -> dict[str, list[str]]:
    """Airport -> destinations bookable on flysafair.co.za."""
    key = "flysafair:network"
    if (hit := cache.get(key, ttl=3 * 86400)) is not None:
        return hit
    cfg = _config()
    r = _s().get(f"{cfg['apiHost']}/api/v1/Airport/OriginsWithConnections/en-za", headers=_headers(cfg), timeout=30)
    r.raise_for_status()
    net = {a["code"]: sorted(c["code"] for c in a.get("connections") or [])
           for a in r.json().get("airports") or []}
    if net:
        cache.put(key, net)
    return net


def relevant(origins: list[str], destinations: list[str]) -> bool:
    try:
        net = network()
    except Exception:
        return False
    return any(d in net.get(o, ()) for o in origins for d in destinations)


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1) -> str:
    u = f"{SITE}/flight/search?fromCityCode={origin}&toCityCode={dest}&departureDateString={dep.isoformat()}"
    if ret:
        u += f"&returnDateString={ret.isoformat()}"
    return u + f"&roundTrip={'true' if ret else 'false'}&adults={adults}&children=0&infants=0"


def parse(data: dict) -> list[tuple[str, str, list[dict]]]:
    """SearchShop JSON -> [(origin, destination, journeys)] per route. Each
    journey keeps the cheapest open fare for all passengers."""
    out = []
    for rt in data.get("routes") or []:
        js = []
        for f in rt.get("flights") or []:
            if f.get("soldOut") or f.get("isPlaceHolder") or not f.get("lowestPriceTotal"):
                continue
            fare = next((x for x in f.get("fares") or [] if x.get("id") == f.get("lowestFareId")), None)
            legs = f.get("legs") or []
            js.append({
                "segments": [{
                    "origin": f["from"]["code"], "destination": f["to"]["code"],
                    "departure": f.get("departureDateTimeOffset") or f["departureDate"],
                    "arrival": f.get("arrivalDateTimeOffset") or f["arrivalDate"],
                    "carrier": f["carrierCode"], "number": f["flightNumber"],
                    "duration": f.get("flightTime"),
                    "aircraft": legs[0].get("equipmentType") if len(legs) == 1 else None,
                }],
                "total": float(f["lowestPriceTotal"]), "fare": fare.get("name") if fare else None,
                "seats": fare.get("seatCount") if fare else None, "duration": f.get("flightTime"),
            })
        out.append((rt["from"]["code"], rt["to"]["code"], js))
    return out


def _fetch(o: str, d: str, dep: date, ret: date | None, adults: int) -> dict:
    key = f"flysafair:{o}:{d}:{dep}:{ret}:{adults}"
    if (hit := cache.get(key)) is not None:
        return hit
    cfg = _config()
    routes = [{"fromAirport": o, "toAirport": d, "startDate": f"{dep}", "endDate": f"{dep}",
               "departureDate": None, "segmentKey": None, "cabin": None}]
    if ret:
        routes.append({"fromAirport": d, "toAirport": o, "startDate": f"{ret}", "endDate": f"{ret}",
                       "departureDate": None, "segmentKey": None, "cabin": None})
    body = {"languageCode": "en-za", "currency": "ZAR", "passengers": [{"code": "ADT", "count": adults}],
            "routes": routes, "promoCode": "", "filterMethod": "102", "fareTypeCategories": [1],
            "isManageBooking": False, "sanlamSubscriptionId": None, "externalProfileId": None,
            "fareTypeFilters": [], "fareClass": None, "apiKey": None}
    host = cfg.get("gcpApiHost") or cfg["apiHost"]
    r = _s().post(f"{host}/api/v1/Availability/SearchShop", data=json.dumps(body), headers=_headers(cfg), timeout=45)
    if r.status_code in (401, 403):
        cache.put("flysafair:config", None)
    r.raise_for_status()
    data = r.json()
    cache.put(key, data)
    return data


def search(q: SearchQuery) -> list[Itinerary]:
    if q.cabin != "economy" or not relevant(q.origins, q.destinations):
        return []
    net = network()
    out: list[Itinerary] = []
    for o in q.origins[:3]:
        for d in q.destinations[:3]:
            if d not in net.get(o, ()):
                continue
            data = _fetch(o, d, q.departure, q.return_date, q.adults)
            bounds = parse(data)
            outs = next((js for a, b, js in bounds if a == o), [])
            backs = next((js for a, b, js in bounds if a == d), []) if q.return_date else None
            if not outs or (q.return_date and not backs):
                continue
            out += combine(q, "flysafair", "FlySafair", outs, backs, data.get("currency") or "ZAR",
                           deeplink(o, d, q.departure, q.return_date, q.adults), NAMES,
                           note="FlySafair Low fare (cheapest; bags and seat extra).")
    return out
