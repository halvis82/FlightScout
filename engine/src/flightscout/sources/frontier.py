"""Frontier (F9) direct from flyfrontier.com. The booking site is server
rendered (Navitaire): GET /Flight/InternalSelect, the URL the search form
itself opens, answers with the select page, and the page carries every
flight and fare as a JSON blob (``FlightData = '...'``, HTML escaped). Plain
HTTP with Chrome TLS impersonation (curl_cffi) gets it, no key or session.

One request covers both directions of a round trip (Frontier prices each
direction on its own; the return prices equal the one way prices). Prices are
per person in USD incl. taxes and fees, what the page shows as "Standard"
(Basic fare, rounded to the dollar there); Discount Den (club) prices are a
dollar or more lower but need a paid membership, so we ignore them. The page
is 1 to 2 MB and takes about 5 to 15 seconds.

Routes come from data/frontier_routes.json, the booking page's own station
list (``airporStations``: every station with the markets it sells, connections
included); refresh it when Frontier changes its network."""

from __future__ import annotations

import html
import json
import re
import threading
from datetime import date
from functools import cache as memo
from pathlib import Path
from urllib.parse import quote

from curl_cffi import requests as cr

from .. import cache
from ..models import Itinerary, SearchQuery
from ._airline import combine

SITE = "https://booking.flyfrontier.com"
_lock = threading.Lock()
_session: cr.Session | None = None
_FLIGHTDATA = re.compile(r"FlightData\s*=\s*'(.*?)';", re.S)


@memo
def routes() -> dict[str, set[str]]:
    raw = json.loads((Path(__file__).parents[1] / "data" / "frontier_routes.json").read_text())
    return {o: set(ds) for o, ds in raw.items()}


def _pairs(origins: list[str], destinations: list[str]) -> list[tuple[str, str]]:
    r = routes()
    return [(o, d) for o in origins for d in destinations if o != d and d in r.get(o, ())]


def relevant(origins: list[str], destinations: list[str]) -> bool:
    return bool(_pairs(origins, destinations))


def _d(day: date) -> str:
    return quote(day.strftime("%b %d, %Y"))


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1) -> str:
    url = f"{SITE}/Flight/InternalSelect?o1={origin}&d1={dest}&dd1={_d(dep)}"
    if ret:
        url += f"&dd2={_d(ret)}&r=true"
    return url + f"&ADT={adults}&mon=true&promo="


def flight_data(page: str) -> dict:
    """The ``FlightData`` JSON embedded in the select page."""
    m = _FLIGHTDATA.search(page)
    if not m:
        raise RuntimeError("frontier: no FlightData on the select page (site change or blocked)")
    return json.loads(html.unescape(m.group(1)))


def parse(data: dict, adults: int = 1) -> tuple[list[dict], list[dict]]:
    """FlightData -> (outbound, return) journeys, Standard (Basic) fare."""
    outs: list[dict] = []
    backs: list[dict] = []
    for j in data.get("journeys") or []:
        dest = backs if j.get("isReturnTrip") else outs
        for f in j.get("flights") or []:
            p = f.get("standardFare")
            if not f.get("isMonetary", True) or not p or p <= 0 or not f.get("legs"):
                continue
            seats = None
            m = re.match(r"(\d+)", str(f.get("standardFareSeatsRemaining") or ""))
            if m:
                seats = int(m.group(1))
            dest.append({
                "segments": [{"origin": l["departureStation"], "destination": l["arrivalStation"],
                              "departure": l["departureDate"],
                              "arrival": l["arrivalDate"], "carrier": l.get("carrierCode") or "F9",
                              "number": l["flightNumber"]} for l in f["legs"]],
                "total": round(float(p) * adults, 2), "seats": seats,
                "duration": _minutes(f["legs"]),
            })
    return outs, backs


def _minutes(legs: list[dict]) -> int | None:
    from datetime import datetime
    try:
        a = datetime.fromisoformat(legs[0]["departureDateUtc"].replace("Z", "+00:00"))
        b = datetime.fromisoformat(legs[-1]["arrivalDateUtc"].replace("Z", "+00:00"))
        return int((b - a).total_seconds() // 60)
    except (KeyError, TypeError, ValueError):
        return None


def _fetch(url: str) -> dict:
    global _session
    with _lock:
        if _session is None:
            _session = cr.Session(impersonate="chrome")
    r = _session.get(url, timeout=45, headers={"Accept": "text/html"})
    r.raise_for_status()
    return flight_data(r.text)


def search(q: SearchQuery) -> list[Itinerary]:
    pairs = _pairs(q.origins, q.destinations)
    if not pairs or q.cabin != "economy":
        return []
    out: list[Itinerary] = []
    for o, d in pairs[:3]:
        url = deeplink(o, d, q.departure, q.return_date, q.adults)
        key = f"frontier:{o}:{d}:{q.departure}:{q.return_date}:{q.adults}"
        if (data := cache.get(key)) is None:
            full = _fetch(url)
            data = {"journeys": full.get("journeys") or []}
            cache.put(key, data)
        outs, backs = parse(data, q.adults)
        if q.return_date and not backs:
            continue
        out += combine(q, "frontier", "Frontier", outs, backs if q.return_date else None, "USD", url,
                       {"F9": "Frontier"}, note="Frontier Basic fare incl. taxes and fees; bags and seats extra.")
    return out
