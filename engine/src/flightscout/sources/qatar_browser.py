"""Qatar Airways (QR) direct from qatarairways.com through the shared real
Chrome (see _browser.py). Akamai answers plain HTTP clients with "Access
Denied" on the booking API, but headless Chrome gets through.

We open the site's own flight selection deeplink
(/app/booking/flight-selection?...) and capture the JSON its booking app
fetches from /dapi/public/bff/web/flight-search/flight-offers: every flight
with each fare family's total price incl. taxes for all passengers, which is
exactly the amount the page lists per cabin. About 15 to 20 seconds per
search, headless.

One way only per page load. Qatar prices round trips as one fare whose
outbound page shows only the outbound share, so a round trip is priced here as
two one way tickets (real, bookable, but usually dearer than Qatar's own
round trip fare; the warning says so).

Relevance: both airports must be on Qatar's own network (its city list,
``priority == "qr"``), in different countries, and a trip via Doha must not
be a silly detour."""

from __future__ import annotations

import json
import logging
from datetime import date

from curl_cffi import requests as cr

from .. import airports, cache, fx
from ..models import Itinerary, SearchQuery
from . import _browser
from ._airline import combine

log = logging.getLogger(__name__)
SITE = "https://www.qatarairways.com"
CITY_LIST = f"{SITE}/content/Qatar/common/cityLists/citylists/cityList_en.json"
NAMES = {"QR": "Qatar Airways"}
_CABIN = {"economy": "ECONOMY", "business": "BUSINESS", "first": "FIRST"}
_BOOKING_CLASS = {"economy": "E", "business": "B", "first": "F"}
_DETOUR = 1.6  # max (o->DOH->d) / (o->d)


def available() -> bool:
    return _browser.available()


def network() -> dict[str, str]:
    """Qatar's own airports -> country code (partner-only airports left out)."""
    key = "qatar:network"
    if (hit := cache.get(key, ttl=7 * 86400)) is not None:
        return hit
    r = cr.get(CITY_LIST, impersonate="chrome", timeout=40)
    r.raise_for_status()
    net = {c["shorthand"]: c.get("countryCode") or "" for c in r.json()
           if c.get("priority") == "qr" and len(c.get("shorthand") or "") == 3}
    if net:
        cache.put(key, net)
    return net


def _via_doha(o: str, d: str) -> bool:
    if "DOH" in (o, d):
        return True
    try:
        direct = airports.haversine_km(o, d)
        return direct > 0 and (airports.haversine_km(o, "DOH") + airports.haversine_km("DOH", d)) / direct <= _DETOUR
    except Exception:
        return False


def _pairs(origins: list[str], destinations: list[str]) -> list[tuple[str, str]]:
    try:
        net = network()
    except Exception:
        return []
    return [(o, d) for o in origins for d in destinations
            if o in net and d in net and o != d and net[o] != net[d] and _via_doha(o, d)]


def relevant(origins: list[str], destinations: list[str]) -> bool:
    return available() and bool(_pairs(origins, destinations))


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1,
             cabin: str = "economy") -> str:
    q = (f"widget=QR&searchType=F&addTaxToFare=Y&minPurTime=0&selLang=en&tripType={'R' if ret else 'O'}"
         f"&fromStation={origin}&toStation={dest}&departing={dep.isoformat()}")
    if ret:
        q += f"&returning={ret.isoformat()}"
    q += (f"&bookingClass={_BOOKING_CLASS.get(cabin, 'E')}&adults={adults}&children=0&infants=0&ofw=0"
          "&teenager=0&flexibleDate=off")
    return f"{SITE}/app/booking/flight-selection?{q}"


def parse(data: dict, cabin: str = "economy") -> tuple[list[dict], str | None]:
    """flight-offers JSON -> (journeys, currency). Each journey keeps its
    cheapest fare family in the cabin; prices are for all passengers."""
    want = _CABIN.get(cabin, "ECONOMY")
    out, currency = [], None
    for fo in data.get("flightOffers") or []:
        fares = [x for x in fo.get("fareOffers") or []
                 if x.get("cabinType") == want and not x.get("mixedCabin") and (x.get("price") or {}).get("total")]
        if not fares:
            continue
        f = min(fares, key=lambda x: x["price"]["total"])
        segs = []
        for s in fo.get("segments") or []:
            fn = s["flightNumber"]
            segs.append({"origin": s["departure"]["origin"]["iataCode"],
                         "destination": s["arrival"]["destination"]["iataCode"],
                         "departure": s["departure"]["dateTime"], "arrival": s["arrival"]["dateTime"],
                         "carrier": fn[:2], "number": fn[2:],
                         "duration": s["duration"] // 60 if s.get("duration") else None,
                         "aircraft": (s.get("vehicle") or {}).get("code")})
        currency = f["price"].get("currencyCode") or currency
        out.append({"segments": segs, "total": float(f["price"]["total"]), "fare": f.get("fareFamilyCode"),
                    "seats": f.get("availableSeats"),
                    "duration": fo["duration"] // 60 if fo.get("duration") else None})
    return out, currency


def _fetch(url: str) -> dict:
    def job(page) -> str:
        got = _browser.capture(page, lambda: page.goto(url, wait_until="commit", timeout=45000),
                               lambda u: "/flight-search/flight-offers" in u, timeout=45)
        return got[-1][1] if got else ""

    txt = _browser.run(job, "qatar", timeout=120)
    if not txt:
        raise RuntimeError("qatar: no flight offers response (blocked or page changed)")
    d = json.loads(txt)
    if "flightOffers" not in d:
        raise RuntimeError(f"qatar: error response {txt[:150]!r}")
    return d


def _bound(o: str, d: str, day: date, adults: int, cabin: str) -> tuple[list[dict], str | None]:
    key = f"qatar:{o}:{d}:{day}:{adults}"
    if (hit := cache.get(key)) is None:
        hit = _fetch(deeplink(o, d, day, adults=adults))
        cache.put(key, hit)
    return parse(hit, cabin)


def search(q: SearchQuery) -> list[Itinerary]:
    if q.cabin not in _CABIN or not available():
        return []
    out: list[Itinerary] = []
    for o, d in _pairs(q.origins, q.destinations)[:2]:
        outs, c1 = _bound(o, d, q.departure, q.adults, q.cabin)
        backs, c2 = _bound(d, o, q.return_date, q.adults, q.cabin) if q.return_date and outs else (None, None)
        if not outs or (q.return_date and not backs):
            continue
        note = "Qatar Airways cheapest fare family in the cabin."
        if q.return_date:
            note += " Priced as two one way tickets; a Qatar round trip fare is usually cheaper."
            if c2 and c1 and c2 != c1:  # each side is priced in its origin's currency
                backs = [{**b, "total": round(fx.convert(b["total"], c2, c1), 2)} for b in backs]
                note += f" The return was priced in {c2} and converted to {c1}."
        out += combine(q, "qatar", "Qatar Airways", outs, backs, c1 or "QAR",
                       deeplink(o, d, q.departure, q.return_date, q.adults, q.cabin), NAMES, note=note)
    return out
