"""United Airlines (UA) direct from united.com through the shared real Chrome
(see _browser.py). United's shopping API (/api/flight/...) answers 428
"Access Denied" (Akamai) to plain HTTP clients even with a valid anonymous
token, but the flight search results page loads fine in headless Chrome.

We open the one way results deeplink (/en/us/fsr/choose-flights?f=SFO&t=LAX
&d=2026-11-12&tt=1&...) and capture the server sent event stream the page
reads (POST /api/flight/FetchSSENestedFlights): one ``data:`` JSON line per
event, ``flightOption`` events carry a flight (first segment at the top level,
the rest in ``connections``) and its fare products (ECO-BASIC, ECONOMY,
ECONOMY-UNRESTRICTED, *-MERCH-EPLUS, MIN-BUSINESS-OR-FIRST...), some nested
under a parent. The ``Fare`` price ``amount`` is the one way price per person
incl. taxes (what the page shows), ``amountAllPax`` the total for everyone.
About 20 to 25 seconds per direction; round trips are two one way searches
(the page prices the outbound of a round trip at the "from" round trip
total)."""

from __future__ import annotations

import json
import logging
from datetime import date

from .. import airports, cache
from ..models import Itinerary, SearchQuery
from . import _browser
from ._airline import combine, countries

log = logging.getLogger(__name__)
SITE = "https://www.united.com"
NAMES = {"UA": "United Airlines"}


def available() -> bool:
    return _browser.available()


def relevant(origins: list[str], destinations: list[str]) -> bool:
    """United's network touches the US (or Guam) on every itinerary it sells."""
    o, d = countries(origins), countries(destinations)
    return bool(o and d and (o | d) & {"US", "GU"}) and available()


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1) -> str:
    q = f"f={origin}&t={dest}&d={dep}"
    if ret:
        q += f"&r={ret}&tt=0&sc=7,7"
    else:
        q += "&tt=1&sc=7"
    return f"{SITE}/en/us/fsr/choose-flights?{q}&px={adults}&taxng=1&newHP=True&clm=7"


def _cabin_ok(p: dict, cabin: str) -> bool:
    t, ct = p.get("productType") or "", (p.get("cabinType") or "").lower()
    if "MERCH" in t:  # Economy Plus: an economy fare plus a paid seat, not a cabin
        return False
    if cabin == "economy":
        return ct == "coach"
    if cabin == "premium":
        return "premium" in ct or "PREMIUM" in t
    return ct in ("first", "business") or "BUSINESS" in t


def _products(f: dict):
    for p in f.get("products") or []:
        yield p
        yield from p.get("nestedProducts") or []


def parse(sse: str, cabin: str = "economy") -> list[dict]:
    """FetchSSENestedFlights event stream -> journey dicts at the cheapest fare
    of the cabin (total for all passengers)."""
    out = []
    for line in sse.splitlines():
        if not line.startswith("data:"):
            continue
        try:
            ev = json.loads(line[5:].strip())
        except ValueError:
            continue
        if ev.get("type") != "flightOption":
            continue
        f = ev.get("flight") or {}
        best = None
        for p in _products(f):
            if not _cabin_ok(p, cabin):
                continue
            fare = next((x for x in p.get("prices") or [] if x.get("pricingType") == "Fare"), None)
            if not fare or fare.get("amount") is None:
                continue
            total = float(fare.get("amountAllPax") or fare["amount"])
            if best is None or total < best[0]:
                best = (total, p.get("productType"))
        if not best:
            continue
        legs = [f] + list(f.get("connections") or [])
        segs = []
        for s in legs:
            dep, arr = s["departDateTime"].replace(" ", "T"), s["destinationDateTime"].replace(" ", "T")
            try:  # UTC offsets make durations exact
                dep += f"{int(s['orgTimezoneOffset']):+03d}:00"
                arr += f"{int(s['destTimezoneOffset']):+03d}:00"
            except (KeyError, TypeError, ValueError):
                pass
            segs.append({"origin": s["origin"], "destination": s["destination"], "departure": dep,
                         "arrival": arr, "carrier": s.get("marketingCarrier") or "UA",
                         "number": s["flightNumber"], "duration": s.get("travelMinutes")})
        out.append({"segments": segs, "total": round(best[0], 2), "fare": best[1],
                    "duration": f.get("travelMinutesTotal")})
    return out


def _fetch(origin: str, dest: str, day: date, adults: int) -> str:
    url = deeplink(origin, dest, day, None, adults)

    def job(page) -> str:
        for _ in range(2):  # a cold first load now and then never fires the search: load once more
            got = _browser.capture(page, lambda: page.goto(url, wait_until="commit", timeout=60000),
                                   lambda u: "/api/flight/FetchSSENestedFlights" in u, timeout=60,
                                   stop=lambda: "Access Denied" in (page.title() or ""))
            if got:
                return got[-1][1]
            log.info("united: no flights response, title %r", page.title())
        return ""

    txt = _browser.run(job, "united", timeout=200)
    if not txt:
        raise RuntimeError("united: no flights response (bot check or site change)")
    return txt


def _flights(origin: str, dest: str, day: date, adults: int, cabin: str) -> list[dict]:
    key = f"united:{origin}:{dest}:{day}:{adults}"
    if (txt := cache.get(key)) is None:
        txt = _fetch(origin, dest, day, adults)
        cache.put(key, txt)
    return parse(txt, cabin)


def search(q: SearchQuery) -> list[Itinerary]:
    if not relevant(q.origins, q.destinations):
        return []
    out: list[Itinerary] = []
    known = [c for c in q.origins if airports.get(c)][:1], [c for c in q.destinations if airports.get(c)][:1]
    for o in known[0]:
        for d in known[1]:
            if o == d:
                continue
            outs = _flights(o, d, q.departure, q.adults, q.cabin)
            backs = _flights(d, o, q.return_date, q.adults, q.cabin) if q.return_date else None
            if q.return_date and not backs:
                continue
            out += combine(q, "united", "United Airlines", outs, backs, "USD",
                           deeplink(o, d, q.departure, q.return_date, q.adults), NAMES,
                           note="United cheapest fare of the cabin (often Basic Economy); "
                                "round trips are two one way fares.")
    return out
