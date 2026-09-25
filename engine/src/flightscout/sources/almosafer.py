"""Almosafer (Saudi Arabia / Gulf OTA, Seera Group) through the shared real
Chrome (see _browser.py). Its search API wants a session token the page mints,
so we open the site's own one way results page headless and read the JSON it
polls (/api/flights/search/<id>) until the search is COMPLETED: every
itinerary with legs, segments and the total price. About 15 to 30 seconds.

From outside the Gulf the site is global.almosafer.com and prices in USD.
Results include nearby airports (DXB-RUH also returns Sharjah); we keep the
requested airports only. One way only: round trips use a different step by
step flow (outbound first, then a return priced against it)."""

from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime

from .. import cache
from ..models import Itinerary, SearchQuery, Segment, Slice
from . import _browser

log = logging.getLogger(__name__)
SITE = "https://global.almosafer.com"
_CABIN = {"economy": "Economy", "premium": "Premium_Economy", "business": "Business", "first": "First"}


def available() -> bool:
    return _browser.available()


def relevant(origins: list[str], destinations: list[str]) -> bool:
    return available()


def deeplink(origin: str, dest: str, dep: date, adults: int = 1, cabin: str = "economy") -> str:
    return f"{SITE}/en/flights/{origin}-{dest}/{dep.isoformat()}/{_CABIN.get(cabin, 'Economy')}/{adults}Adult"


def parse(data: dict, url: str = "") -> list[Itinerary]:
    """Completed /api/flights/search/<id> JSON -> one way Itineraries."""
    d = data.get("data") or {}
    segs = {s["segmentId"]: s for s in d.get("segments") or []}
    fares = {f["fareId"]: f for f in d.get("fares") or []}
    out = []
    for it in d.get("itineraries") or []:
        price = (it.get("price") or {}).get("tripPrice") or (it.get("price") or {}).get("itineraryPrice")
        legs = it.get("legs") or []
        if not price or price.get("total") is None or len(legs) != 1:
            continue
        leg, ss, seats = legs[0], [], []
        for ref in leg.get("segmentRefs") or []:
            s = segs.get(ref["segmentId"])
            if not s:
                break
            carrier = s.get("marketingCarrier") or "??"
            code = str(s.get("flightCode") or "")
            ss.append(Segment(
                origin=s["departureAirport"]["code"], destination=s["arrivalAirport"]["code"],
                departure=datetime.fromisoformat(s["departureDateTime"]),
                arrival=datetime.fromisoformat(s["arrivalDateTime"]), carrier=carrier,
                flight_number=code.split("-", 1)[-1] if code else None, duration_min=s.get("durationMin"),
                aircraft=(s.get("aircraftType") or {}).get("name")))
            if (f := fares.get(ref.get("fareId"))) and f.get("seatsRemaining"):
                seats.append(f["seatsRemaining"])
        else:
            if not ss:
                continue
            bags = {b["baggageType"]: b for f in (fares.get(r.get("fareId")) for r in leg["segmentRefs"]) if f
                    for b in f.get("baggage") or []}
            warn = ["Sold by Almosafer (online travel agency), not the airline."]
            if seats and min(seats) <= 3:
                warn.append(f"Only {min(seats)} seats left at this Almosafer price.")
            out.append(Itinerary(
                source="almosafer", price=round(float(price["total"]), 2), currency=price["currency"],
                slices=[Slice(segments=ss, duration_min=max(1, leg.get("durationMin") or 1))],
                booking_url=url, seller="Almosafer", seller_kind="ota",
                baggage={"checked": 1 if "CHECKIN_BAGGAGE" in bags else 0,
                         "hand": 1 if "CABIN_BAGGAGE" in bags else 0} if bags else None,
                warnings=warn,
            ))
    return out


def _fetch(url: str) -> dict:
    def job(page) -> str:
        got: list[str] = []

        def on(r):
            if "/api/flights/search/" in r.url and r.request.method == "GET" and r.ok:
                try:
                    got.append(r.body().decode("utf-8", "replace"))
                except Exception as e:
                    log.debug("almosafer body: %s", e)

        page.on("response", on)
        try:
            page.goto("about:blank")
            page.goto(url, wait_until="commit", timeout=45000)
            end = time.time() + 60
            while time.time() < end:
                page.wait_for_timeout(500)
                if got and '"IN_PROGRESS"' not in got[-1][:600]:
                    break
        finally:
            page.remove_listener("response", on)
        return got[-1] if got else ""

    txt = _browser.run(job, "almosafer", timeout=150)
    if not txt:
        raise RuntimeError("almosafer: no search response")
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
            if (data := cache.get(f"almosafer:{url}", ttl=1800)) is None:
                data = _fetch(url)
                cache.put(f"almosafer:{url}", data)
            for it in parse(data, url):
                if (it.slices[0].origin, it.slices[0].destination) != (o, d):
                    continue
                if q.max_stops is not None and it.slices[0].stops > q.max_stops:
                    continue
                out.append(it)
    return sorted(out, key=lambda i: i.price)
