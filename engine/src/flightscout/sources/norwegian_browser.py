"""Norwegian (DY, D8) direct from norwegian.com through the shared real Chrome
(see _browser.py). Cloudflare shows plain HTTP clients a "Just a moment"
challenge; real Chrome (even headless) passes it by itself.

We open the site's own deeplink (/en/start/booking/avaday/?...), which hands
the search to the Amadeus booking app on booking.norwegian.com, and capture
the air-bounds JSON that app fetches from api-des.norwegian.com: every flight
and fare family with its total price incl. taxes. About 8 to 12 seconds per
search, headless. Round trips are priced as two one ways (Norwegian prices
each direction on its own)."""

from __future__ import annotations

import json
import logging
from datetime import date

from .. import cache
from ..models import Itinerary, SearchQuery
from . import _browser
from ._airline import combine, countries

log = logging.getLogger(__name__)
SITE = "https://www.norwegian.com"
NAMES = {"DY": "Norwegian", "D8": "Norwegian", "DU": "Norwegian"}
NORDIC = {"NO", "SE", "DK", "FI"}
# Where Norwegian flies from the Nordics: Europe, the Mediterranean and a few
# long hauls it sells on partner connections.
COUNTRIES = NORDIC | {
    "IS", "GB", "IE", "FR", "BE", "NL", "DE", "AT", "CH", "ES", "PT", "IT", "GR", "HR", "MT", "CY", "PL",
    "CZ", "HU", "LV", "LT", "EE", "BG", "RO", "SI", "ME", "AL", "TR", "MA", "TN", "EG", "IL", "US",
}


def available() -> bool:
    return _browser.available()


def relevant(origins: list[str], destinations: list[str]) -> bool:
    if not available():
        return False
    o, d = countries(origins), countries(destinations)
    return bool(o and d and (o | d) <= COUNTRIES and NORDIC & (o | d))


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1,
             currency: str = "EUR") -> str:
    q = (f"AdultCount={adults}&A_City={dest}&D_City={origin}&D_Month={dep:%Y%m}&D_Day={dep:%d}"
         f"&IncludeTransit=true&TripType={2 if ret else 1}&CurrencyCode={currency}")
    if ret:
        q += f"&R_Month={ret:%Y%m}&R_Day={ret:%d}"
    return f"{SITE}/en/start/booking/avaday/?{q}"


def parse(data: dict) -> tuple[list[dict], str | None]:
    """Amadeus DES air-bounds JSON -> (journeys, currency). Each journey keeps
    its cheapest fare family."""
    dic = data.get("dictionaries") or {}
    flights = dic.get("flight") or {}
    cur_dec = {k: v.get("decimalPlaces", 2) for k, v in (dic.get("currency") or {}).items()}
    out, currency = [], None
    for g in (data.get("data") or {}).get("airBoundGroups") or []:
        best = None
        for b in g.get("airBounds") or []:
            tp = ((b.get("prices") or {}).get("totalPrices") or [None])[0]
            if not tp:
                continue
            p = tp["total"] / 10 ** cur_dec.get(tp["currencyCode"], 2)
            if best is None or p < best[0]:
                seats = min((a.get("quota") or 99 for a in b.get("availabilityDetails") or []), default=None)
                best = (p, tp["currencyCode"], b.get("fareFamilyCode"), seats)
        if not best:
            continue
        segs = []
        for s in g["boundDetails"]["segments"]:
            f = flights.get(s["flightId"])
            if not f:
                break
            segs.append({"origin": f["departure"]["locationCode"], "destination": f["arrival"]["locationCode"],
                         "departure": f["departure"]["dateTime"], "arrival": f["arrival"]["dateTime"],
                         "carrier": f["marketingAirlineCode"],
                         "number": f["marketingFlightNumber"],
                         "duration": (f["duration"] // 60) if f.get("duration") else None})
        else:
            dur = g["boundDetails"].get("duration")
            out.append({"segments": segs, "total": best[0], "fare": best[2], "seats": best[3],
                        "duration": dur // 60 if dur else None})
            currency = best[1]
    return out, currency


def _fetch(url: str, origin: str = "") -> dict:
    """air-bounds JSON, or {} when Norwegian has no flights that day (it then
    redirects to its low fare calendar page instead of the booking app)."""
    def job(page) -> tuple[str, str]:
        for attempt in range(2):
            got = _browser.capture(page, lambda: page.goto(url, wait_until="commit", timeout=45000),
                                   lambda u: "/search/air-bounds" in u, timeout=40,
                                   stop=lambda: "/low-fare-calendar" in page.url)
            if got:
                # the requested bound: the app may also fetch another (an upsell) after it
                for _, txt in got:
                    try:
                        g = (json.loads(txt).get("data") or {}).get("airBoundGroups") or []
                    except ValueError:
                        continue
                    if not origin or not g or (g[0].get("boundDetails") or {}).get("originLocationCode") == origin:
                        return txt, ""
                return got[0][1], ""
            if "/low-fare-calendar" in page.url:  # "No flights available on selected dates"
                return "", "none"
        return "", page.url

    txt, why = _browser.run(job, "norwegian", timeout=150)
    if why == "none":
        return {}
    if not txt:
        raise RuntimeError(f"norwegian: no availability response (ended on {why[:80]})")
    d = json.loads(txt)
    if "data" not in d:
        raise RuntimeError(f"norwegian: error response {txt[:150]!r}")
    return d


def _bound(o: str, d: str, day: date, adults: int, cur: str) -> tuple[list[dict], str | None]:
    key = f"norwegian:{o}:{d}:{day}:{adults}:{cur}"
    if (hit := cache.get(key)) is None:
        hit = _fetch(deeplink(o, d, day, adults=adults, currency=cur), o)
        cache.put(key, hit)
    return parse(hit)


def search(q: SearchQuery) -> list[Itinerary]:
    if not relevant(q.origins, q.destinations):
        return []
    cur = "EUR"  # the /en site prices in EUR whatever CurrencyCode says; search() converts
    out: list[Itinerary] = []
    for o in q.origins[:2]:
        for d in q.destinations[:2]:
            if o == d:
                continue
            outs, c1 = _bound(o, d, q.departure, q.adults, cur)
            backs, c2 = _bound(d, o, q.return_date, q.adults, cur) if q.return_date and outs else (None, None)
            if not outs or (q.return_date and not backs):
                continue
            out += combine(q, "norwegian", "Norwegian", outs, backs, c1 or cur,
                           deeplink(o, d, q.departure, q.return_date, q.adults, cur), NAMES,
                           note="Norwegian cheapest fare family (usually LowFare, checked bags extra).")
    return out
