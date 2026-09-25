"""Traveloka (Southeast Asia OTA) through the shared real Chrome (see
_browser.py). Plain HTTP clients get DataDome and AWS WAF challenges; a
headless Chrome passes them. We open the site's own one way results page
(en-id, prices in IDR) and capture the flight/search/initial JSON it posts:
every itinerary with segments and the per adult fare. About 10 to 20 seconds.

One way only (round trips are picked step by step, outbound then return).
Prices are per adult as the site shows them, multiplied by the number of
adults; search() converts IDR to the query currency."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime

from .. import cache
from ..models import Itinerary, SearchQuery, Segment, Slice
from . import _browser

log = logging.getLogger(__name__)
SITE = "https://www.traveloka.com"
_CABIN = {"economy": "ECONOMY", "premium": "PREMIUM_ECONOMY", "business": "BUSINESS", "first": "FIRST"}


def available() -> bool:
    return _browser.available()


def relevant(origins: list[str], destinations: list[str]) -> bool:
    return available()


def deeplink(origin: str, dest: str, dep: date, adults: int = 1, cabin: str = "economy") -> str:
    return (f"{SITE}/en-id/flight/fullsearch?ap={origin}.{dest}&dt={dep:%d-%m-%Y}.NA&ps={adults}.0.0"
            f"&sc={_CABIN.get(cabin, 'ECONOMY')}")


def _when(d: dict, t: dict) -> datetime:
    return datetime(int(d["year"]), int(d["month"]), int(d["day"]), int(t["hour"]), int(t["minute"]))


def _money(x: dict) -> tuple[float, str]:
    cv = x["currencyValue"]
    return int(cv["amount"]) / 10 ** int(x.get("numOfDecimalPoint") or 0), cv["currency"]


def parse(data: dict, adults: int = 1, url: str = "") -> list[Itinerary]:
    """flight/search/initial JSON -> one way Itineraries."""
    d = data.get("data") or {}
    names = {k: v.get("name") for k, v in (d.get("airlineDataMap") or {}).items()}
    out = []
    for r in d.get("searchResults") or []:
        fare = (r.get("fare") or {}).get("adult")
        routes = r.get("connectingFlightRoutes") or []
        if not fare or len(routes) != 1:
            continue
        price, cur = _money(fare)
        segs = []
        for s in routes[0].get("segments") or []:
            carrier, _, num = str(s.get("flightNumber") or "").partition("-")
            carrier = s.get("airlineCode") or carrier or "??"
            segs.append(Segment(
                origin=s["departureAirport"], destination=s["arrivalAirport"],
                departure=_when(s["departureDate"], s["departureTime"]),
                arrival=_when(s["arrivalDate"], s["arrivalTime"]), carrier=carrier,
                carrier_name=names.get(carrier), flight_number=num or None,
                duration_min=int(s["durationMinutes"]) if s.get("durationMinutes") else None,
                aircraft=s.get("aircraftType") or None))
        if not segs:
            continue
        meta = r.get("flightMetadata") or {}
        st = bool(meta.get("isSelfTransfer"))
        warn = ["Sold by Traveloka (online travel agency), not the airline."]
        if st:
            warn.append("Self transfer: separate tickets combined by Traveloka, the connection is not protected.")
        out.append(Itinerary(
            source="traveloka", price=round(price * adults, 2), currency=cur,
            slices=[Slice(segments=segs, duration_min=max(1, int(meta.get("tripDuration") or 1)))],
            booking_url=url, seller="Traveloka", seller_kind="ota", self_transfer=st, warnings=warn,
        ))
    return out


def _fetch(url: str) -> dict:
    def job(page) -> str:
        got = _browser.capture(page, lambda: page.goto(url, wait_until="commit", timeout=45000),
                               lambda u: "/api/v2/flight/search/initial" in u, timeout=45)
        return got[-1][1] if got else ""

    txt = _browser.run(job, "traveloka", timeout=120)
    if not txt:
        raise RuntimeError("traveloka: no search response")
    return json.loads(txt)


def search(q: SearchQuery) -> list[Itinerary]:
    if q.return_date or not available():
        return []
    out: list[Itinerary] = []
    for o in q.origins[:1]:
        for d in q.destinations[:1]:
            if o == d:
                continue
            url = deeplink(o, d, q.departure, q.adults, q.cabin)
            if (data := cache.get(f"traveloka:{url}", ttl=1800)) is None:
                data = _fetch(url)
                cache.put(f"traveloka:{url}", data)
            for it in parse(data, q.adults, url):
                sl = it.slices[0]
                if (sl.origin, sl.destination) == (o, d) and (q.max_stops is None or sl.stops <= q.max_stops):
                    out.append(it)
    return sorted(out, key=lambda i: i.price)
