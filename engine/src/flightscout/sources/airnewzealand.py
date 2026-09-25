"""Air New Zealand (NZ) direct from airnewzealand.co.nz, New Zealand domestic
flights only.

No key and no browser: the site's own search deeplink
(flightbookings.airnewzealand.co.nz/vbook/actions/ext-search?...) redirects to
the server rendered flight selection page, which embeds every flight option
with every fare (seat, seat+bag, flexichange, flexirefund) as JSON in a
``VUI.pageInit([...])`` call. One plain HTTP request (Chrome TLS) per search,
round trips included (both legs come back on the same page).

Prices are per passenger in NZD incl. taxes ("Fares per passenger"), so they
are multiplied by the number of adults: selecting NZ611 + NZ612 for 2 adults on
the site shows "Total cost NZD $1,478.00" = (389 + 350) x 2. A domestic round
trip costs the sum of its two legs.

International searches are handed to a different, client rendered booking app
(/fly/select-flights) that this source does not read, so relevant() only
accepts searches with both ends in New Zealand."""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import date

from curl_cffi import requests as cr

from .. import cache
from ..models import Itinerary, SearchQuery
from ._airline import combine, countries

SITE = "https://flightbookings.airnewzealand.co.nz"
NAMES = {"NZ": "Air New Zealand"}
_MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
_FARES = {"ds": "seat", "db": "seat+bag", "dc": "flexichange", "df": "flexirefund"}
_INIT = re.compile(r'VUI\.pageInit\(\[(?=\{"config")')
_lock = threading.Lock()
_last = 0.0
_MIN_GAP = 1.0  # seconds between searches, to stay polite


def relevant(origins: list[str], destinations: list[str]) -> bool:
    o, d = countries(origins), countries(destinations)
    return bool(o and d and (o | d) == {"NZ"})


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1) -> str:
    legs = [(origin, dest, dep)] + ([(dest, origin, ret)] if ret else [])
    q = "&".join(
        f"searchLegs%5B{i}%5D.originPoint={a}&searchLegs%5B{i}%5D.destinationPoint={b}"
        f"&searchLegs%5B{i}%5D.tripStartMonth={_MONTHS[d.month - 1]}&searchLegs%5B{i}%5D.tripStartDate={d.day}"
        for i, (a, b, d) in enumerate(legs))
    q += (f"&depart-from={origin}&depart-to={dest}&tripType={'return' if ret else 'oneway'}&adults={adults}"
          "&children=0&infants=0&bookingClass=ECONOMY&promoCode=&searchType=flexible&doSearch=search")
    return f"{SITE}/vbook/actions/ext-search?{q}"


def page_data(html: str) -> dict | None:
    """The ``{"config": ..., "data": {"legs": [...]}}`` object of the flight
    selection page, or None when the page has no flight list."""
    dec = json.JSONDecoder()
    for m in _INIT.finditer(html):
        try:
            obj, _ = dec.raw_decode(html, m.end())
        except ValueError:
            continue
        if isinstance(obj.get("data"), dict) and "legs" in obj["data"]:
            return obj
    return None


def parse(data: dict, adults: int = 1) -> tuple[list[list[dict]], str | None]:
    """flight selection page data -> ([journeys per leg], currency). Each
    journey keeps its cheapest fare (usually "seat": carry on only)."""
    bounds, currency = [], None
    for leg in (data.get("data") or {}).get("legs") or []:
        out = []
        for opt in leg.get("legOptions") or []:
            prices = [(c["s-price"], c.get("code")) for band in opt.get("costs") or []
                      for c in band.get("costs") or [] if isinstance(c.get("s-price"), (int, float))]
            if not prices or not opt.get("flights"):
                continue
            price, code = min(prices)
            currency = opt.get("currency") or currency
            segs = [{
                "origin": f["originAirport"]["airport"]["code"],
                "destination": f["destinationAirport"]["airport"]["code"],
                "departure": f["originAirport"]["dateTimeLocal"], "arrival": f["destinationAirport"]["dateTimeLocal"],
                "carrier": f["flightNumber"][:2], "number": f["flightNumber"][2:].lstrip("0") or "0",
                "aircraft": (f.get("equipment") or {}).get("shortDesc"),
            } for f in opt["flights"]]
            if len(segs) == 1:
                segs[0]["duration"] = opt.get("s-duration")
            out.append({"segments": segs, "total": round(price * adults, 2), "fare": _FARES.get(code, code),
                        "duration": opt.get("s-duration"), "date": leg.get("date")})
        bounds.append(out)
    return bounds, currency


def _fetch(url: str) -> dict | None:
    global _last
    with _lock:
        wait = _MIN_GAP - (time.time() - _last)
        if wait > 0:
            time.sleep(wait)
        _last = time.time()
    # A fresh session per search: the site keeps the search in the session.
    with cr.Session(impersonate="chrome") as s:
        r = s.get(url, timeout=60)
    r.raise_for_status()
    if "/vbook/actions/selectitinerary" not in r.url:
        return None  # sent to the international app or back to the search form: nothing to read
    return page_data(r.text)


def search(q: SearchQuery) -> list[Itinerary]:
    if not relevant(q.origins, q.destinations):
        return []
    out: list[Itinerary] = []
    for o in q.origins[:2]:
        for d in q.destinations[:2]:
            if o == d:
                continue
            key = f"airnewzealand:{o}:{d}:{q.departure}:{q.return_date}:{q.adults}"
            if (data := cache.get(key)) is None:
                data = _fetch(deeplink(o, d, q.departure, q.return_date, q.adults)) or {}
                cache.put(key, data)
            bounds, cur = parse(data, q.adults) if data else ([], None)
            want = [q.departure] + ([q.return_date] if q.return_date else [])
            # the deeplink has no year and the site may clamp a date: keep only exact matches
            bounds = [[j for j in b if j["date"] == [w.year, w.month, w.day]] for b, w in zip(bounds, want)]
            if len(bounds) != len(want) or not all(bounds):
                continue
            out += combine(q, "airnewzealand", "Air New Zealand", bounds[0], bounds[1] if q.return_date else None,
                           cur or "NZD", deeplink(o, d, q.departure, q.return_date, q.adults), NAMES,
                           note="Air New Zealand cheapest fare (usually \"seat\": carry on only).")
    return out
