"""VivaAerobus (VB) flight list direct from vivaaerobus.com through the shared
real Chrome (see _browser.py). The low fare calendar works over plain HTTP
(vivaaerobus.py), but the flight list endpoint sits behind Akamai Bot Manager,
which rejects curl_cffi and headless Chrome alike. A headful Chrome passes, so
this source runs in the shared headful browser (window off screen and
minimized) and is skipped where there is no display (Linux without X).

We open the booking deeplink (/en-us/book/options?itineraryCode=...) and
capture the JSON the page posts to api.vivaaerobus.com/web/v1/availability/search.
One call covers both directions of a round trip. ``fareWithTua`` is the fare
incl. the TUA airport fee (what the page shows), per passenger, in USD on the
en-us site. About 12 to 16 seconds per search."""

from __future__ import annotations

import json
import logging
from datetime import date

from .. import cache
from ..models import Itinerary, SearchQuery
from . import _browser
from ._airline import combine, countries

log = logging.getLogger(__name__)
SITE = "https://www.vivaaerobus.com"
COUNTRIES = {"MX", "US", "CO", "PE", "GT", "CU"}


def available() -> bool:
    return _browser.available(headful=True)


def relevant(origins: list[str], destinations: list[str]) -> bool:
    if not available():
        return False
    o, d = countries(origins), countries(destinations)
    return bool(o and d and (o | d) <= COUNTRIES and "MX" in (o | d))


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1) -> str:
    code = f"{origin}_{dest}_{dep:%Y%m%d}" + (f".{dest}_{origin}_{ret:%Y%m%d}" if ret else "")
    return f"{SITE}/en-us/book/options?itineraryCode={code}&passengers=A{adults}"


def _minutes(hms: str | None) -> int | None:
    try:
        h, m, *_ = (hms or "").split(":")
        days, _, h = h.rpartition(".")  # "1.02:30:00" past 24 hours
        return int(days or 0) * 1440 + int(h) * 60 + int(m)
    except ValueError:
        return None


def parse(data: dict, adults: int = 1) -> tuple[list[list[dict]], str]:
    """availability/search JSON -> (journeys per route, currency)."""
    d = data.get("data") or {}
    cur = d.get("currencyCode") or "USD"
    bounds = []
    for r in d.get("routes") or []:
        out = []
        for j in r.get("journeys") or []:
            if j.get("isSoldout"):
                continue
            best = None
            for f in j.get("fares") or []:
                if f.get("fareBookingType") == "Points":
                    continue
                amt = (f.get("fareWithTua") or f.get("fare") or {}).get("amount")
                if amt is not None and (best is None or amt < best[0]):
                    best = (float(amt), f.get("availableCount"))
            if not best:
                continue
            segs = [{"origin": s["origin"]["code"], "destination": s["destination"]["code"],
                     "departure": s["departureDate"], "arrival": s["arrivalDate"],
                     "carrier": s.get("marketingCarrier") or "VB",
                     "number": s.get("marketingCode") or s["flightNumber"].removeprefix("VB"),
                     "aircraft": s.get("equipmentType"), "duration": _minutes(s.get("segmentDuration"))}
                    for s in j.get("segments") or []]
            if segs:  # times are local without offsets, so keep Viva's own durations
                out.append({"segments": segs, "total": round(best[0] * adults, 2), "seats": best[1],
                            "duration": _minutes(j.get("journeyDuration"))})
        bounds.append(out)
    return bounds, cur


def _fetch(url: str) -> dict:
    def job(page) -> str:
        for _ in range(2):  # Akamai sometimes holds the first request of a session
            got = _browser.capture(page, lambda: page.goto(url, wait_until="commit", timeout=45000),
                                   lambda u: "api.vivaaerobus.com/web/v1/availability/search" in u, timeout=30)
            if got:
                return got[-1][1]
        return ""

    txt = _browser.run(job, "vivaaerobus", headful=True, timeout=150)
    if not txt:
        raise RuntimeError("vivaaerobus: no availability response")
    d = json.loads(txt)
    if "data" not in d:
        raise RuntimeError(f"vivaaerobus: blocked or error: {txt[:150]!r}")
    return d


def search(q: SearchQuery) -> list[Itinerary]:
    if not relevant(q.origins, q.destinations):
        return []
    out: list[Itinerary] = []
    for o in q.origins[:2]:
        for d in q.destinations[:2]:
            if o == d:
                continue
            url = deeplink(o, d, q.departure, q.return_date, q.adults)
            key = f"vivabrowser:{o}:{d}:{q.departure}:{q.return_date}:{q.adults}"
            if (data := cache.get(key)) is None:
                data = _fetch(url)
                cache.put(key, data)
            bounds, cur = parse(data, q.adults)
            if not bounds or (q.return_date and len(bounds) < 2):
                continue
            out += combine(q, "vivaaerobus", "VivaAerobus", bounds[0], bounds[1] if q.return_date else None, cur,
                           url, {"VB": "VivaAerobus"}, note="Viva Base fare incl. TUA airport fee, bags extra.")
    return out
