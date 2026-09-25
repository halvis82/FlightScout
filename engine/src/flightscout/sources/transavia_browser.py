"""Transavia (HV Netherlands, TO France) direct from transavia.com through the
shared real Chrome (see _browser.py). Google and Kiwi only cover part of the
Transavia network (Orly to Lisbon or Porto is often missing), so this fills a
real gap.

Cloudflare answers 403 to every fetch()/XHR the booking page makes from an
automated browser, but plain document navigations pass. So we navigate to the
booking deeplink (it stores the search in the TransaviaFlightSearch cookie)
and then navigate to the JSON endpoint the page itself would call,
/start/api/flight-availability, and read it as the page body. About one to
three seconds per search, headless.

Prices are per person in EUR incl. taxes (what the select page shows); round
trips are the sum of the two one ways, as Transavia sells them."""

from __future__ import annotations

import json
import logging
from datetime import date

from .. import cache
from ..models import Itinerary, SearchQuery
from . import _browser
from ._airline import combine, countries

log = logging.getLogger(__name__)
SITE = "https://www.transavia.com"
API = f"{SITE}/start/api/flight-availability?type=full&update=false"
NAMES = {"HV": "Transavia", "TO": "Transavia France"}

# Transavia bases (NL, France, Brussels). Every route touches one of them.
BASES = {"AMS", "RTM", "EIN", "GRQ", "ORY", "NTE", "LYS", "MPL", "MRS", "BRU", "BOD", "LIL"}
# Countries Transavia flies to: Europe, the Mediterranean, North Africa,
# Middle East and Cape Verde.
COUNTRIES = {
    "NL", "FR", "BE", "ES", "PT", "IT", "GR", "HR", "MT", "CY", "AT", "CH", "DE", "IE", "GB", "DK", "SE",
    "NO", "FI", "IS", "CZ", "HU", "PL", "BG", "RO", "SI", "ME", "AL", "RS", "BA", "MK", "TR", "MA", "TN",
    "DZ", "EG", "IL", "JO", "LB", "CV", "SN", "GM",
}


def available() -> bool:
    return _browser.available()


def relevant(origins: list[str], destinations: list[str]) -> bool:
    if not available():
        return False
    o, d = set(origins), set(destinations)
    return bool((o & BASES and countries(destinations) & COUNTRIES)
                or (d & BASES and countries(origins) & COUNTRIES))


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1) -> str:
    q = f"ds={origin}&as={dest}&od={dep.day}&om={dep.month}&oy={dep.year}&r={'True' if ret else 'False'}"
    if ret:
        q += f"&id={ret.day}&im={ret.month}&iy={ret.year}"
    return f"{SITE}/book/en-eu/search-a-flight?{q}&ap={adults}&cp=0&ip=0"


def parse(data: dict, adults: int = 1) -> tuple[list[dict], list[dict] | None]:
    """flight-availability JSON -> (outbound journeys, inbound journeys or None)."""
    d = data.get("data") or {}

    def bound(b: dict | None) -> list[dict]:
        out = []
        for s in (b or {}).get("timeSlots") or []:
            if s.get("price") is None:
                continue
            fn = s["flightNumber"]
            dep, arr = s["departureDateTime"], s["arrivalDateTime"]
            out.append({
                "segments": [{"origin": b["departure"], "destination": b["arrival"], "departure": dep,
                              "arrival": arr, "carrier": fn[:2], "number": fn[2:]}],
                "total": float(s["price"]) * adults, "seats": s.get("availabilityCount"),
            })
        return out

    return bound(d.get("outboundFlight")), (bound(d["inboundFlight"]) if d.get("inboundFlight") else None)


def _fetch(url: str) -> dict:
    def job(page) -> str:
        # the API answers "Invalid flight availability request" until the
        # site language cookie exists (the page's scripts normally set it)
        page.context.add_cookies([{"name": "SearchSite.SiteLang", "value": "en-eu",
                                   "domain": "www.transavia.com", "path": "/"}])
        txt = ""
        for mode in ("commit", "domcontentloaded"):
            try:
                page.goto(url, wait_until=mode, timeout=12000 if mode == "commit" else 25000)
                if mode != "commit":  # second try: let the page settle its cookies
                    page.wait_for_timeout(1500)
                page.goto(API, wait_until="commit", timeout=25000)
                txt = page.inner_text("body")
            except Exception as e:
                log.info("transavia %s attempt failed: %s", mode, str(e).splitlines()[0])
                continue
            if '"data"' in txt:
                break
        return txt

    txt = _browser.run(job, "transavia", timeout=90)
    try:
        return json.loads(txt)
    except ValueError:
        raise RuntimeError(f"transavia: unexpected page: {txt[:120]!r}") from None


def search(q: SearchQuery) -> list[Itinerary]:
    if not relevant(q.origins, q.destinations):
        return []
    out: list[Itinerary] = []
    for o in q.origins[:3]:
        for d in q.destinations[:3]:
            if o == d or not (o in BASES or d in BASES):
                continue
            url = deeplink(o, d, q.departure, q.return_date, q.adults)
            key = f"transavia:{o}:{d}:{q.departure}:{q.return_date}:{q.adults}"
            data = cache.get(key)
            if data is None:
                data = _fetch(url)
                if "data" not in data:  # "Invalid ... request": Transavia doesn't fly it
                    data = {"data": {}}
                cache.put(key, data)
            outs, backs = parse(data, q.adults)
            if q.return_date and backs is None:
                continue
            out += combine(q, "transavia", "Transavia", outs, backs if q.return_date else None, "EUR", url, NAMES)
    return out
