"""Finnair (AY) direct from finnair.com through the shared real Chrome (see
_browser.py). Akamai answers plain HTTP clients (even with Chrome TLS) 403 on
api.finnair.com, but headless Chrome passes.

We open the site's own flight selection deeplink
(/en/booking/flight-selection?json=...) and capture the ``airBounds`` JSON
the page fetches from api.finnair.com/d/fcom/offers-prod: every flight
(nonstop and connections via Helsinki) with every fare family and its price
incl. taxes and fees, in the currency of the departure country (EUR from
Finland, SEK from Sweden, ...; a round trip's return is converted). About 8 to 15 seconds per
direction, headless. Round trips are priced as two one ways (each is a real
Finnair one way ticket; Finnair's own round trip fare can differ)."""

from __future__ import annotations

import json
import logging
from datetime import date
from urllib.parse import quote

from .. import cache, fx
from ..models import Itinerary, SearchQuery
from . import _browser
from ._airline import combine, countries

log = logging.getLogger(__name__)
SITE = "https://www.finnair.com"
NAMES = {"AY": "Finnair"}
# Finnair sells from its Helsinki hub to Europe, Asia, the Middle East and
# North America. A ticket either touches Finland or connects in Helsinki,
# which only makes sense between Europe and the long haul markets.
EUROPE = {
    "FI", "SE", "NO", "DK", "IS", "EE", "LV", "LT", "PL", "DE", "NL", "BE", "LU", "FR", "GB", "IE", "CH", "AT",
    "CZ", "HU", "SK", "SI", "HR", "IT", "ES", "PT", "GR", "CY", "MT", "RO", "BG", "AL", "ME", "RS", "TR", "EG",
    "MA",
}
LONG_HAUL = {"JP", "KR", "CN", "HK", "TW", "TH", "SG", "VN", "IN", "AE", "QA", "US", "CA", "LK", "MV", "KE",
             "TZ", "MU"}
_CABIN = {"economy": "ECONOMY", "premium": "ECOPREMIUM", "business": "BUSINESS", "first": "BUSINESS"}


def available() -> bool:
    return _browser.available()


def relevant(origins: list[str], destinations: list[str]) -> bool:
    if not available():
        return False
    o, d = countries(origins), countries(destinations)
    if not o or not d:
        return False
    if "FI" in o | d:
        return True
    return bool((o <= EUROPE and d <= LONG_HAUL) or (d <= EUROPE and o <= LONG_HAUL))


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1) -> str:
    flights = [{"origin": origin, "destination": dest, "departureDate": dep.isoformat()}]
    if ret:
        flights.append({"origin": dest, "destination": origin, "departureDate": ret.isoformat()})
    js = {"flights": flights, "cabin": "MIXED", "adults": adults, "c15s": 0, "children": 0, "infants": 0}
    return f"{SITE}/en/booking/flight-selection?json={quote(json.dumps(js, separators=(',', ':')), safe=':,')}"


def parse(data: dict, cabin: str = "economy") -> tuple[list[dict], str | None]:
    """airBounds JSON -> (journeys, currency). Each journey keeps its cheapest
    fare family in the wanted cabin (every segment in that cabin)."""
    want = _CABIN.get(cabin, "ECONOMY")
    families = data.get("fareFamilies") or {}
    out = []
    for g in data.get("boundGroups") or []:
        best = None
        for ff in g.get("fareFamilies") or []:
            cabins = {fi.get("cabinClass") for fi in ff.get("fareInformation") or []}
            if cabins != {want}:
                continue
            p = float(ff.get("totalPrice") or ff["price"])
            if best is None or p < best[0]:
                best = (p, ff.get("fareFamilyCode"), ff.get("quota"))
        if not best:
            continue
        det = g["details"]
        segs = []
        for s in det.get("itinerary") or []:
            if s.get("type", "FLIGHT") != "FLIGHT":
                continue  # layover entries
            fn = s["flightNumber"]
            segs.append({"origin": s["departure"]["locationCode"], "destination": s["arrival"]["locationCode"],
                         "departure": s["departure"]["dateTime"], "arrival": s["arrival"]["dateTime"],
                         "carrier": fn[:2], "number": fn[2:],
                         "duration": (s.get("duration") or {}).get("milliseconds", 0) // 60000 or None,
                         "aircraft": (s.get("aircraft") or {}).get("name")})
        if not segs:
            continue
        name = (families.get(best[1]) or {}).get("brandName") or best[1]
        dur = (det.get("duration") or {}).get("milliseconds")
        out.append({"segments": segs, "total": best[0], "fare": name, "seats": best[2],
                    "duration": dur // 60000 if dur else None})
    return out, data.get("currency")


def _fetch(url: str) -> dict:
    def go(page):
        for _ in range(3):
            try:
                page.goto(url, wait_until="commit", timeout=45000)
                return
            except Exception as e:  # a fresh profile's first navigation is often aborted
                log.debug("finnair goto: %s", e)
                page.wait_for_timeout(1000)

    def job(page) -> str:
        for _ in range(2):
            got = _browser.capture(page, lambda: go(page),
                                   lambda u: "/offers-prod/current/api/airBounds" in u, timeout=40)
            if got:
                return got[-1][1]
        return ""

    txt = _browser.run(job, "finnair", timeout=120)
    if not txt:
        raise RuntimeError("finnair: no availability response")
    d = json.loads(txt)
    if d.get("boundGroups") is None:
        if d.get("status") == "NO_FLIGHTS_FOUND":  # no Finnair flights that day
            return {}
        raise RuntimeError(f"finnair: error response {txt[:150]!r}")
    return d


def _bound(o: str, d: str, day: date, adults: int, cabin: str) -> tuple[list[dict], str | None]:
    key = f"finnair:{o}:{d}:{day}:{adults}"
    if (hit := cache.get(key)) is None:
        hit = _fetch(deeplink(o, d, day, adults=adults))
        cache.put(key, hit)
    return parse(hit, cabin)


def search(q: SearchQuery) -> list[Itinerary]:
    if not relevant(q.origins, q.destinations):
        return []
    out: list[Itinerary] = []
    for o in q.origins[:2]:
        for d in q.destinations[:2]:
            if o == d:
                continue
            outs, c1 = _bound(o, d, q.departure, q.adults, q.cabin)
            backs, c2 = _bound(d, o, q.return_date, q.adults, q.cabin) if q.return_date and outs else (None, None)
            if not outs or (q.return_date and not backs):
                continue
            if backs and c1 and c2 and c2 != c1:  # each direction is priced in its origin's currency
                backs = [{**b, "total": round(fx.convert(b["total"], c2, c1), 2)} for b in backs]
            note = "Finnair cheapest fare family in this cabin."
            if q.return_date:
                note += " Priced as two one way tickets."
            out += combine(q, "finnair", "Finnair", outs, backs, c1 or "EUR",
                           deeplink(o, d, q.departure, q.return_date, q.adults), NAMES, note=note)
    return out
