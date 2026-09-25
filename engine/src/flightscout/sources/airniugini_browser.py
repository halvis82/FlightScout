"""Air Niugini (PX, Papua New Guinea) direct from its Sabre booking app
(dx-flights.airniugini.com.pg, Sabre Digital Experience) through the shared
headless Chrome (see _browser.py). Flag carrier of Papua New Guinea: the
domestic network plus Brisbane, Sydney, Cairns, Manila, Singapore, Hong Kong,
Tokyo, Nadi and Honiara, which the metasearch sites carry only partly.

The home page's search form posts to WordPress, which redirects to a plain
GET deeplink of the booking app (``/dx/PXDX/#/flight-selection?...``). We open
that deeplink headless and capture the app's own ``bookingAirSearch``
GraphQL answer (/api/graphql). The app sits behind Imperva: the first search
of a fresh browser goes straight through, and the shared tab keeps the
cookies for the next ones. About 12 to 16 seconds per direction.

Prices: each brand offer's ``total`` is the fare plus taxes (607 + 343.20 =
950.20 PGK) and the page says "The fares displayed below are inclusive of all
applicable taxes. Fares are in PGK and ONE WAY per adult passenger".
Mandatory carrier fees (``totalMandatoryObFees``), when present, are added.
The amounts are per adult (a 2 adult search returns the same 950.20), so we
multiply by the number of adults.
Verified September 2026 (headless): POM-BNE 22 Oct 2026 PX3 950.20 PGK here
and "From 950.20 PGK" on the flight selection page (PX5 950.20 both).
Round trips are two one way searches (each a real one way ticket)."""

from __future__ import annotations

import json
import logging
from datetime import date

from .. import cache, fx
from ..models import Itinerary, SearchQuery
from . import _browser
from ._airline import combine, countries

log = logging.getLogger(__name__)
SITE = "https://dx-flights.airniugini.com.pg"
NAMES = {"PX": "Air Niugini"}
_CABIN = {"economy": "Economy", "premium": "Economy", "business": "Business", "first": "Business"}


def available() -> bool:
    return _browser.available()


def relevant(origins: list[str], destinations: list[str]) -> bool:
    """Every Air Niugini flight touches Papua New Guinea."""
    if not available():
        return False
    return "PG" in countries(origins) or "PG" in countries(destinations)


def deeplink(origin: str, dest: str, dep: date, adults: int = 1) -> str:
    d = f"{dep:%m-%d-%Y}"
    return (f"{SITE}/dx/PXDX/?#/flight-selection?journeyType=one-way&activeMonth={d}&date={d}"
            f"&origin={origin}&destination={dest}&ADT={adults}&CHD=0&INF=0&promoCode=")


def _refs(o, ids: dict) -> None:
    if isinstance(o, dict):
        if "@id" in o:
            ids[o["@id"]] = o
        for v in o.values():
            _refs(v, ids)
    elif isinstance(o, list):
        for v in o:
            _refs(v, ids)


def _amount(x: dict | None) -> tuple[float, str | None]:
    alts = (x or {}).get("alternatives") or []
    tot, cur = 0.0, None
    for a in (alts[0] if alts else []):
        tot += float(a.get("amount") or 0)
        cur = cur or a.get("currency")
    return tot, cur


def parse(data: dict, cabin: str = "economy", adults: int = 1) -> tuple[list[dict], str | None]:
    """bookingAirSearch GraphQL JSON -> (journeys, currency), cheapest brand
    of the cabin per itinerary. Brand offer amounts are per adult (the same
    950.20 comes back for a 2 adult search), so the total is times ``adults``."""
    r = (((data.get("data") or {}).get("bookingAirSearch") or {}).get("originalResponse")) or {}
    if not isinstance(r, dict):
        return [], None
    ids: dict = {}
    _refs(r, ids)
    want = _CABIN.get(cabin, "Economy")
    out, currency = [], r.get("currency")
    parts = (r.get("brandedResults") or {}).get("itineraryPartBrands") or []
    for e in (parts[0] if parts else []):
        ip = e.get("itineraryPart") or {}
        if "@ref" in ip:
            ip = ids.get(ip["@ref"], {})
        best = None
        for o in e.get("brandOffers") or []:
            if o.get("soldout") or o.get("cabinClass") != want or not o.get("total"):
                continue
            tot, cur = _amount(o["total"])
            tot += _amount(o.get("totalMandatoryObFees"))[0]
            if tot > 0 and (best is None or tot < best[0]):
                best = (tot, cur, o.get("brandId"), (o.get("seatsRemaining") or {}).get("count"))
        segs = []
        for s in ip.get("segments") or []:
            if "@ref" in s:
                s = ids.get(s["@ref"], {})
            f = s.get("flight") or {}
            if not s.get("origin"):
                break
            segs.append({"origin": s["origin"], "destination": s["destination"],
                         "departure": s["departure"] + (s.get("departureGMTOffset") or ""),
                         "arrival": s["arrival"] + (s.get("arrivalGMTOffset") or ""),
                         "carrier": f.get("airlineCode") or "PX", "number": str(f.get("flightNumber")),
                         "duration": s.get("duration"), "aircraft": s.get("equipment")})
        else:
            if best and segs:
                out.append({"segments": segs, "total": round(best[0] * adults, 2), "fare": best[2], "seats": best[3],
                            "duration": ip.get("totalDuration") or e.get("duration")})
                currency = best[1] or currency
    return out, currency


def _fetch(o: str, d: str, day: date, adults: int) -> dict:
    key = f"airniugini:{o}:{d}:{day}:{adults}"
    if (hit := cache.get(key)) is not None:
        return hit
    url = deeplink(o, d, day, adults)

    def job(page) -> str:
        if page.url.startswith(SITE):  # a hash route change alone would not search again
            page.goto("about:blank")
        got = _browser.capture(page, lambda: page.goto(url, wait_until="domcontentloaded", timeout=45000),
                               lambda u: "/api/graphql" in u, timeout=40,
                               body=lambda t: '"bookingAirSearch"' in t)
        return got[0][1] if got else ""

    txt = _browser.run(job, "airniugini", timeout=120)
    if not txt:
        raise RuntimeError("airniugini: no availability response (blocked by Imperva or page changed)")
    data = json.loads(txt)
    if not ((data.get("data") or {}).get("bookingAirSearch") or {}).get("originalResponse"):
        raise RuntimeError(f"airniugini: error response {txt[:150]!r}")
    cache.put(key, data)
    return data


def search(q: SearchQuery) -> list[Itinerary]:
    if not relevant(q.origins, q.destinations):
        return []
    out: list[Itinerary] = []
    pairs = [(o, d) for o in q.origins for d in q.destinations
             if o != d and "PG" in countries([o]) | countries([d])][:2]
    for o, d in pairs:
        outs, cur = parse(_fetch(o, d, q.departure, q.adults), q.cabin, q.adults)
        backs, cur2 = (parse(_fetch(d, o, q.return_date, q.adults), q.cabin, q.adults) if q.return_date and outs
                       else (None, None))
        if not outs or (q.return_date and not backs):
            continue
        note = "Air Niugini cheapest fare brand in the cabin, incl. taxes."
        if cur2 and cur and cur2 != cur:
            backs = [{**b, "total": round(fx.convert(b["total"], cur2, cur), 2)} for b in backs]
            note += f" The return was priced in {cur2} and converted to {cur}."
        out += combine(q, "airniugini", "Air Niugini", outs, backs, cur or "PGK",
                       deeplink(o, d, q.departure, q.adults), NAMES, note=note)
    return out
