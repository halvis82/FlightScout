"""Cleartrip (India OTA, Flipkart group) through the shared real Chrome (see
_browser.py). Its search API sits behind Akamai (plain HTTP gets "Access
Denied"), so we open the site's own one way results page headless and capture
the JSON it fetches (/flight/search/v2): every travel option with flights and
fares. Prices in INR incl. taxes for all passengers. About 15 to 25 seconds.

We keep each option's cheapest fare, and only the requested airports (the
site mixes in nearby ones, e.g. Navi Mumbai for BOM). One way only: round
trips use a different split screen flow."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime

from .. import airports, cache
from ..models import Itinerary, SearchQuery, Segment, Slice
from . import _browser

log = logging.getLogger(__name__)
SITE = "https://www.cleartrip.com"
_CABIN = {"economy": "Economy", "premium": "Premium Economy", "business": "Business", "first": "First"}


def available() -> bool:
    return _browser.available()


def relevant(origins: list[str], destinations: list[str]) -> bool:
    return available()


def deeplink(origin: str, dest: str, dep: date, adults: int = 1, cabin: str = "economy") -> str:
    a, b = airports.get(origin), airports.get(dest)
    intl = "n" if a and b and a.country == b.country == "IN" else "y"
    return (f"{SITE}/flights/results?adults={adults}&childs=0&infants=0&class={_CABIN.get(cabin, 'Economy')}"
            f"&depart_date={dep:%d/%m/%Y}&from={origin}&to={dest}&intl={intl}").replace(" ", "%20")


def _dt(p: dict) -> datetime:
    return datetime.fromisoformat(p["airport"]["time"]).replace(tzinfo=None)


def parse(data: dict, url: str = "") -> list[Itinerary]:
    """/flight/search/v2 JSON -> one way Itineraries (cheapest fare each)."""
    flights, fares = data.get("flights") or {}, data.get("fares") or {}
    names = {k: (v or {}).get("name") for k, v in
             ((data.get("metaData") or {}).get("airlineDetail") or {}).items()}
    out = []
    for sto in (data.get("subTravelOptions") or {}).values():
        if sto.get("type") != "flight":
            continue
        best = None
        for fid in sto.get("fareIds") or []:
            p = (((fares.get(fid) or {}).get("pricing") or {}).get("totalPricing") or {}).get("totalPrice")
            if p is not None and (best is None or p < best):
                best = p
        seq = sto.get("sequenceToFlightIdMap") or {}
        legs = [flights.get(seq[k]) for k in sorted(seq, key=int)]
        if best is None or not legs or None in legs:
            continue
        segs = []
        for f in legs:
            carrier = f.get("marketingAirlineCode") or f.get("airlineCode") or "??"
            dur = f.get("duration") or {}
            segs.append(Segment(
                origin=f["departure"]["airport"]["code"], destination=f["arrival"]["airport"]["code"],
                departure=_dt(f["departure"]), arrival=_dt(f["arrival"]), carrier=carrier,
                carrier_name=names.get(carrier), flight_number=str(f.get("fltNo") or "") or None,
                duration_min=dur.get("hh", 0) * 60 + dur.get("mm", 0) if dur else None))
        first = datetime.fromisoformat(legs[0]["departure"]["airport"]["time"])
        last = datetime.fromisoformat(legs[-1]["arrival"]["airport"]["time"])
        out.append(Itinerary(
            source="cleartrip", price=round(float(best), 2), currency="INR",
            slices=[Slice(segments=segs, duration_min=max(1, int((last - first).total_seconds() // 60)))],
            booking_url=url, seller="Cleartrip", seller_kind="ota",
            warnings=["Sold by Cleartrip (online travel agency), not the airline."],
        ))
    return out


def _fetch(url: str) -> dict:
    def job(page) -> str:
        got = _browser.capture(page, lambda: page.goto(url, wait_until="commit", timeout=45000),
                               lambda u: "/flight/search/v2" in u, timeout=45)
        return got[-1][1] if got else ""

    txt = _browser.run(job, "cleartrip", timeout=120)
    if not txt:
        raise RuntimeError("cleartrip: no search response")
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
            if (data := cache.get(f"cleartrip:{url}", ttl=1800)) is None:
                data = _fetch(url)
                cache.put(f"cleartrip:{url}", data)
            for it in parse(data, url):
                sl = it.slices[0]
                if (sl.origin, sl.destination) == (o, d) and (q.max_stops is None or sl.stops <= q.max_stops):
                    out.append(it)
    return sorted(out, key=lambda i: i.price)
