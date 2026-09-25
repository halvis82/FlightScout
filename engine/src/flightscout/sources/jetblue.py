"""JetBlue (B6) direct from jetblue.com's own flight search API, the one the
results page calls: POST /api/ecom/cb-flight-search/v1/search/NGB. Plain HTTP
with Chrome TLS impersonation (curl_cffi) is enough for the API (the results
page itself sits behind a Fastly client challenge, the API does not).

Key: the page sends an Azure APIM ``ocp-apim-subscription-key``, a public
client key. We read it at runtime from the site's own front end logger
script (home page -> static.jetblue.com/.../felog/felog.js), never hardcoded.

One request per direction (JetBlue prices each direction on its own; we sum
two one way searches for a round trip), about 2 to 6 seconds each. Price =
cheapest Economy fare family (usually Blue Basic) per person incl. taxes, the
amount the results page shows (rounded there to the dollar). Routes come
from data/jetblue_routes.json (the site's own od-service route list, own
metal and JetBlue sold connections)."""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import date
from functools import cache as memo
from pathlib import Path

from curl_cffi import requests as cr

from .. import cache
from ..models import Itinerary, SearchQuery
from ._airline import combine

SITE = "https://www.jetblue.com"
API = SITE + "/api/ecom/cb-flight-search/v1/search/NGB"
_lock = threading.Lock()
_session: cr.Session | None = None
_key: tuple[str, float] | None = None
_CABIN = {"economy": "Economy", "premium": "Economy", "business": "Business", "first": "Business"}


@memo
def routes() -> dict[str, set[str]]:
    raw = json.loads((Path(__file__).parents[1] / "data" / "jetblue_routes.json").read_text())
    return {o: set(ds) for o, ds in raw.items()}


def _pairs(origins: list[str], destinations: list[str]) -> list[tuple[str, str]]:
    r = routes()
    return [(o, d) for o in origins for d in destinations if o != d and d in r.get(o, ())]


def relevant(origins: list[str], destinations: list[str]) -> bool:
    return bool(_pairs(origins, destinations))


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1) -> str:
    return (f"{SITE}/booking/flights?from={origin}&to={dest}&depart={dep}"
            + (f"&return={ret}" if ret else "")
            + f"&isMultiCity=false&noOfRoute=1&adults={adults}&children=0&infants=0&sharedMarket=false"
              f"&roundTripFaresFlag=false&usePoints=false")


def _api_key() -> str:
    """The public APIM key, from the site's own logger script."""
    global _session, _key
    with _lock:
        if _session is None:
            _session = cr.Session(impersonate="chrome")
        if _key and time.time() - _key[1] < 12 * 3600:
            return _key[0]
        if (hit := cache.get("jetblue-key", ttl=12 * 3600)):
            _key = (hit, time.time())
            return hit
        home = _session.get(SITE + "/", timeout=30).text
        m = re.search(r'https://static\.jetblue\.com/[\w/]+/felog/felog\.js', home)
        if not m:
            raise RuntimeError("jetblue: logger script not found on the home page (site change)")
        js = _session.get(m.group(0), timeout=30).text
        k = re.search(r"subscriptionKey:\s*['\"]([0-9a-f]{32})['\"]", js)
        if not k:
            raise RuntimeError("jetblue: no subscription key in the logger script (site change)")
        _key = (k.group(1), time.time())
        cache.put("jetblue-key", k.group(1))
        return k.group(1)


def parse(data: dict, adults: int = 1, cabin: str = "economy") -> list[dict]:
    """NGB response -> journeys, cheapest available fare family of the cabin."""
    want = _CABIN.get(cabin, "Economy")
    out = []
    for sr in ((data.get("data") or {}).get("searchResults")) or []:
        for po in sr.get("productOffers") or []:
            best = None
            for o in po.get("offers") or []:
                if o.get("soldOut") or o.get("cabinClass") != want or not o.get("price"):
                    continue
                p = float(o["price"][0]["amount"])
                if best is None or p < best[0]:
                    best = (p, o["price"][0].get("currency") or "USD", (o.get("seatsRemaining") or {}).get("count"),
                            (o.get("brand") or {}).get("brandId"))
            ods = po.get("originAndDestination") or []
            if not best or not ods:
                continue
            od = ods[0]
            segs = [{"origin": s["departure"]["airport"], "destination": s["arrival"]["airport"],
                     "departure": s["departure"]["date"], "arrival": s["arrival"]["date"],
                     "carrier": s["flightInfo"].get("marketingAirlineCode") or "B6",
                     "number": s["flightInfo"]["marketingFlightNumber"], "duration": s.get("duration"),
                     "aircraft": s.get("aircraft")} for s in od.get("flightSegments") or []]
            if not segs:
                continue
            out.append({"segments": segs, "total": round(best[0] * adults, 2), "currency": best[1],
                        "seats": best[2], "brand": best[3], "duration": od.get("totalDuration")})
    return out


def _fetch(o: str, d: str, day: date, adults: int) -> dict:
    key = _api_key()
    body = {"awardBooking": False, "travelerTypes": [{"type": "ADULT", "quantity": adults}],
            "searchComponents": [{"from": o, "to": d, "date": day.isoformat()}]}
    h = {"ocp-apim-subscription-key": key, "accept": "application/json, text/plain, */*",
         "content-type": "application/json", "Origin": SITE, "Referer": deeplink(o, d, day, None, adults)}
    r = _session.post(API, json=body, headers=h, timeout=45)
    if r.status_code in (401, 403):  # key rotated: fetch it again next time
        global _key
        _key = None
        cache.put("jetblue-key", None)
    r.raise_for_status()
    return r.json()


def _journeys(o: str, d: str, day: date, adults: int, cabin: str) -> list[dict]:
    key = f"jetblue:{o}:{d}:{day}:{adults}"
    if (data := cache.get(key)) is None:
        data = _fetch(o, d, day, adults)
        cache.put(key, data)
    # NGB prices the whole party: amounts are per person (checked with 2 adults)
    return [j for j in parse(data, adults, cabin) if j["segments"][0]["departure"][:10] == str(day)]


def search(q: SearchQuery) -> list[Itinerary]:
    pairs = _pairs(q.origins, q.destinations)
    if not pairs:
        return []
    out: list[Itinerary] = []
    for o, d in pairs[:2]:
        outs = _journeys(o, d, q.departure, q.adults, q.cabin)
        backs = _journeys(d, o, q.return_date, q.adults, q.cabin) if q.return_date else None
        if q.return_date and not backs:
            continue
        out += combine(q, "jetblue", "JetBlue", outs, backs, "USD", deeplink(o, d, q.departure, q.return_date, q.adults),
                       {"B6": "JetBlue"}, note="JetBlue cheapest fare family (usually Blue Basic) incl. taxes.")
    return out
