"""Aerolíneas Argentinas (AR) direct from aerolineas.com.ar's own shopping API
(api.aerolineas.com.ar/v1/flights/offers). Aerolíneas prices in ARS for its
Argentine point of sale and Google often shows only USD fares from other
markets, so this fills the domestic Argentina gap.

No key of ours: the web app embeds an anonymous client-credentials token in
every page (``window.__ACCESS_TOKEN__``), which we read from the home page at
runtime (valid about a day, refreshed hourly here). Plain HTTP with Chrome TLS
impersonation (curl_cffi) is enough.

``fare.total`` is the per adult price incl. taxes and charges, exactly what
the results page shows per fare family (verified: AR1526 AEP-COR 2026-11-10
Base, ARS 60.147 on the site and in the API). A round trip search prices each
direction separately (cheaper than two one ways); the page shows the same per
direction numbers (AR1526 57.352 + AR1551 80.883 for 10/17 Nov)."""

from __future__ import annotations

import re
import threading
import time
from datetime import date

from curl_cffi import requests as cr

from .. import cache
from ..models import Itinerary, SearchQuery
from ._airline import combine, countries

SITE = "https://www.aerolineas.com.ar"
API = "https://api.aerolineas.com.ar/v1"
NAMES = {"AR": "Aerolíneas Argentinas"}
# Every Aerolíneas route touches Argentina; these are the countries it flies to.
COUNTRIES = {"AR", "BR", "CL", "UY", "PY", "BO", "PE", "CO", "EC", "US", "ES", "IT", "DO", "CU", "MX", "AW", "VE"}

_lock = threading.Lock()
_session: cr.Session | None = None
_token: tuple[str, float] | None = None
_last = 0.0
_MIN_GAP = 0.5


def relevant(origins: list[str], destinations: list[str]) -> bool:
    o, d = countries(origins), countries(destinations)
    return bool(o and d and (o | d) <= COUNTRIES and "AR" in (o | d))


def _headers() -> dict:
    global _session, _token, _last
    with _lock:
        if _session is None:
            _session = cr.Session(impersonate="chrome")
        if not _token or time.time() - _token[1] > 3600:
            r = _session.get(SITE + "/", timeout=30)
            r.raise_for_status()
            m = re.search(r'window\.__ACCESS_TOKEN__\s*=\s*"([^"]+)"', r.text)
            if not m:
                raise RuntimeError("aerolineas: no access token on the home page (site change)")
            _token = (m.group(1), time.time())
        wait = _MIN_GAP - (time.time() - _last)
        if wait > 0:
            time.sleep(wait)
        _last = time.time()
        return {"Authorization": "Bearer " + _token[0], "Referer": SITE + "/", "Origin": SITE,
                "Accept": "application/json"}


def _params(legs: list[tuple[str, str, date]], adults: int) -> list[tuple[str, str]]:
    p = [("adt", str(adults)), ("inf", "0"), ("chd", "0"), ("flexDates", "false"), ("cabinClass", "Economy"),
         ("flightType", "ROUND_TRIP" if len(legs) == 2 else "ONE_WAY")]
    return p + [("leg", f"{o}-{d}-{day:%Y%m%d}") for o, d, day in legs]


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1) -> str:
    legs = [(origin, dest, dep)] + ([(dest, origin, ret)] if ret else [])
    return f"{SITE}/flights-offers?" + "&".join(f"{k}={v}" for k, v in _params(legs, adults))


def parse(data: dict, adults: int = 1) -> tuple[list[list[dict]], str]:
    """offers JSON -> (journeys per direction, currency). Each journey is the
    cheapest available fare family on that flight, priced for ``adults``."""
    cur = (data.get("searchMetadata") or {}).get("currency") or "ARS"
    bounds = []
    offers = data.get("brandedOffers") or {}
    for k in sorted(offers, key=int):
        out = []
        for x in offers[k] or []:
            best = None
            for o in x.get("offers") or []:
                seats = (o.get("seatAvailability") or {}).get("seats")
                total = (o.get("fare") or {}).get("total")
                if not total or seats == 0:
                    continue
                if best is None or total < best[0]:
                    best = (float(total), o, seats)
            if not best:
                continue
            legs = x.get("legs") or []
            segs = [{"origin": s["origin"], "destination": s["destination"], "departure": s["departure"],
                     "arrival": s["arrival"], "carrier": s.get("airline") or "AR", "number": s["flightNumber"],
                     "duration": s.get("duration"), "aircraft": s.get("equipment")}
                    for leg in legs for s in leg.get("segments") or []]
            if not segs:
                continue
            out.append({"segments": segs, "total": round(best[0] * adults, 2), "seats": best[2],
                        "fare": (best[1].get("brand") or {}).get("name"),
                        "duration": sum(leg.get("totalDuration") or 0 for leg in legs) or None})
        bounds.append(out)
    return bounds, cur


def _search(o: str, d: str, dep: date, ret: date | None, adults: int) -> dict:
    key = f"aerolineas:{o}:{d}:{dep}:{ret}:{adults}"
    if (hit := cache.get(key)) is not None:
        return hit
    legs = [(o, d, dep)] + ([(d, o, ret)] if ret else [])
    r = _session_get(f"{API}/flights/offers", _params(legs, adults))
    cache.put(key, r)
    return r


def _session_get(url: str, params) -> dict:
    h = _headers()
    r = _session.get(url, params=params, headers=h, timeout=40)
    if r.status_code in (400, 404):  # route not flown / no availability
        return {}
    r.raise_for_status()
    return r.json()


def search(q: SearchQuery) -> list[Itinerary]:
    if not relevant(q.origins, q.destinations) or q.cabin not in ("economy", "premium"):
        return []
    out: list[Itinerary] = []
    for o in q.origins[:3]:
        for d in q.destinations[:3]:
            if o == d:
                continue
            bounds, cur = parse(_search(o, d, q.departure, q.return_date, q.adults), q.adults)
            if not bounds or (q.return_date and len(bounds) < 2):
                continue
            out += combine(q, "aerolineas", "Aerolíneas Argentinas", bounds[0],
                           bounds[1] if q.return_date else None, cur,
                           deeplink(o, d, q.departure, q.return_date, q.adults), NAMES,
                           note="Aerolíneas cheapest available fare family (usually Base, carry on only).")
    return out
