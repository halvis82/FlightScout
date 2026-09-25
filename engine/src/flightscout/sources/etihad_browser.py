"""Etihad Airways (EY) direct from etihad.com through the shared real Chrome
(see _browser.py). The booking app (digital.etihad.com, Amadeus Digital
Experience) sits behind Akamai; headless Chrome gets through, plain HTTP does
not.

We open the site's own search deeplink (digital.etihad.com/book/search?...)
and capture the air-bounds JSON the app fetches from api-des.etihad.com (the
app gets its own anonymous OAuth token first): every flight with each fare
family's total price incl. taxes for all passengers. About 15 to 25 seconds
per search, headless. The first load now and then lands on a bare /book/
page; we retry once.

One way per page load. Like Qatar, Etihad's round trip fares are one price
shown half on each page, so a round trip here is two one way tickets (real
and bookable, usually dearer than Etihad's round trip fare; the warning says
so).

Relevance: both airports in Etihad's reference data (its network plus
partners), different countries, and a trip via Abu Dhabi is not a silly
detour."""

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
SITE = "https://digital.etihad.com"
REFDATA = "https://www.etihad.com/ada-services/coredata/service/v1/reference-data?language=en"
NAMES = {"EY": "Etihad Airways"}
_CABIN = {"economy": ("E", "eco"), "business": ("B", "business"), "first": ("F", "first")}
_DETOUR = 1.6


def available() -> bool:
    return _browser.available()


def network() -> set[str]:
    key = "etihad:network"
    if (hit := cache.get(key, ttl=7 * 86400)) is not None:
        return set(hit)
    r = cr.get(REFDATA, impersonate="chrome", timeout=40)
    r.raise_for_status()
    net = sorted(k for k in (r.json().get("airport-code-to-airport-name") or {}) if len(k) == 3)
    if net:
        cache.put(key, net)
    return set(net)


def _via_auh(o: str, d: str) -> bool:
    if "AUH" in (o, d):
        return True
    try:
        direct = airports.haversine_km(o, d)
        return direct > 0 and (airports.haversine_km(o, "AUH") + airports.haversine_km("AUH", d)) / direct <= _DETOUR
    except Exception:
        return False


def _pairs(origins: list[str], destinations: list[str]) -> list[tuple[str, str]]:
    try:
        net = network()
    except Exception:
        return []
    out = []
    for o in origins:
        for d in destinations:
            a, b = airports.get(o), airports.get(d)
            if o in net and d in net and a and b and a.country != b.country and _via_auh(o, d):
                out.append((o, d))
    return out


def relevant(origins: list[str], destinations: list[str]) -> bool:
    return available() and bool(_pairs(origins, destinations))


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1,
             cabin: str = "economy") -> str:
    q = (f"LANGUAGE=EN&CHANNEL=DESKTOP&B_LOCATION={origin}&E_LOCATION={dest}&TRIP_TYPE={'R' if ret else 'O'}"
         f"&CABIN={_CABIN.get(cabin, _CABIN['economy'])[0]}&TRAVELERS={','.join(['ADT'] * adults)}"
         f"&TRIP_FLOW_TYPE=AVAILABILITY&SITE_EDITION=EN-US&DATE_1={dep:%Y%m%d}0000")
    if ret:
        q += f"&DATE_2={ret:%Y%m%d}0000"
    return f"{SITE}/book/search?{q}"


def parse(data: dict, cabin: str = "economy") -> tuple[list[dict], str | None]:
    """Amadeus DES air-bounds JSON -> (journeys, currency), cheapest fare
    family per flight in the cabin, total for all passengers."""
    want = _CABIN.get(cabin, _CABIN["economy"])[1]
    dic = data.get("dictionaries") or {}
    flights = dic.get("flight") or {}
    cur_dec = {k: v.get("decimalPlaces", 0) for k, v in (dic.get("currency") or {}).items()}
    out, currency = [], None
    for g in (data.get("data") or {}).get("airBoundGroups") or []:
        best = None
        for b in g.get("airBounds") or []:
            av = b.get("availabilityDetails") or []
            if not av or any(a.get("cabin") != want for a in av) or b.get("isSoldOut"):
                continue
            tp = ((b.get("prices") or {}).get("totalPrices") or [None])[0]
            if not tp:
                continue
            p = tp["total"] / 10 ** cur_dec.get(tp["currencyCode"], 0)
            if best is None or p < best[0]:
                best = (p, tp["currencyCode"], b.get("fareFamilyCode"),
                        min((a.get("quota") or 99 for a in av), default=None))
        if not best:
            continue
        segs = []
        for s in g["boundDetails"]["segments"]:
            f = flights.get(s["flightId"])
            if not f:
                break
            segs.append({"origin": f["departure"]["locationCode"], "destination": f["arrival"]["locationCode"],
                         "departure": f["departure"]["dateTime"], "arrival": f["arrival"]["dateTime"],
                         "carrier": f["marketingAirlineCode"], "number": f["marketingFlightNumber"],
                         "duration": (f["duration"] // 60) if f.get("duration") else None,
                         "aircraft": f.get("aircraftCode")})
        else:
            dur = g["boundDetails"].get("duration")
            out.append({"segments": segs, "total": best[0], "fare": best[2], "seats": best[3],
                        "duration": dur // 60 if dur else None})
            currency = best[1]
    return out, currency


def _fetch(url: str) -> dict:
    def job(page) -> str:
        for _ in range(2):
            got = _browser.capture(page, lambda: page.goto(url, wait_until="commit", timeout=45000),
                                   lambda u: "/search/air-bounds" in u, timeout=40,
                                   body=lambda t: '"airBoundGroups"' in t or '"errors"' in t)
            if got:
                return got[0][1]  # the first bound call is the requested date and cabins
        return ""

    txt = _browser.run(job, "etihad", timeout=150)
    if not txt:
        raise RuntimeError("etihad: no availability response (blocked or page changed)")
    d = json.loads(txt)
    if "data" not in d:
        if "errors" in d:  # e.g. no flights that day
            return {"data": {"airBoundGroups": []}}
        raise RuntimeError(f"etihad: error response {txt[:150]!r}")
    return d


def _bound(o: str, d: str, day: date, adults: int, cabin: str) -> tuple[list[dict], str | None]:
    key = f"etihad:{o}:{d}:{day}:{adults}:{cabin}"
    if (hit := cache.get(key)) is None:
        hit = _fetch(deeplink(o, d, day, adults=adults, cabin=cabin))
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
        note = "Etihad cheapest fare family in the cabin."
        if q.return_date:
            note += " Priced as two one way tickets; an Etihad round trip fare is usually cheaper."
            if c2 and c1 and c2 != c1:  # each side is priced in its origin's currency
                backs = [{**b, "total": round(fx.convert(b["total"], c2, c1), 2)} for b in backs]
                note += f" The return was priced in {c2} and converted to {c1}."
        out += combine(q, "etihad", "Etihad Airways", outs, backs, c1 or "AED",
                       deeplink(o, d, q.departure, q.return_date, q.adults, q.cabin), NAMES, note=note)
    return out
