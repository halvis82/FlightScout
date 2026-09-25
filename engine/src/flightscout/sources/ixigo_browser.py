"""ixigo (ixigo.com, India) through its results page in the shared headless
Chrome: the page streams its offers from /flights/v2/search/stream
(text/event-stream, 2 events, about 600 kB) and we read that answer. The
stream needs a device session the page sets up itself, so a plain HTTP
client is not enough.

``displayFare`` is the price the results list shows, for all passengers incl.
taxes, after ixigo's automatic instant discount (``slashedFare`` is the
struck through price before it). Connections only come with their journey
times, not per segment, so only nonstop flights are returned. One way only
(ixigo prices domestic round trips as two one ways; search each way).
Prices in INR. 10 to 20 seconds per search.

Unofficial: fails soft."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from .. import cache
from ..models import Itinerary, SearchQuery, Segment, Slice
from . import _browser

SITE = "https://www.ixigo.com"
_CABIN = {"economy": "e", "premium": "w", "business": "b", "first": "f"}
NOTE = "Sold by ixigo (Indian travel agency), not the airline; a convenience fee may be added at checkout."


def relevant(origins: list[str], destinations: list[str]) -> bool:
    return _browser.available()


def search_url(o: str, d: str, dep: date, adults: int = 1, cabin: str = "economy") -> str:
    return (f"{SITE}/search/result/flight?from={o}&to={d}&date={dep:%d%m%Y}&adults={adults}&children=0&infants=0"
            f"&class={_CABIN.get(cabin, 'e')}&source=Search+Form")


def events(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        if line.startswith("data:"):
            try:
                out.append(json.loads(line[5:]).get("data") or {})
            except ValueError:
                continue
    return out


def parse(text: str, q: SearchQuery, o: str, d: str) -> list[Itinerary]:
    """The search stream -> nonstop Itineraries, cheapest fare per flight."""
    url = search_url(o, d, q.departure, q.adults, q.cabin)
    best: dict[str, Itinerary] = {}
    for ev in events(text):
        for fj in ev.get("flightJourneys") or []:
            for f in fj.get("flightFare") or []:
                keys = (f.get("flightKeys") or "").split("*")
                det = (f.get("flightDetails") or [{}])[0]
                if len(keys) != 1 or not det.get("departureTime"):
                    continue  # connections: no per segment times
                parts = keys[0].split("-")  # BOM-DEL-SG613-12112026
                if len(parts) != 4 or parts[0] != o or parts[1] != d:
                    continue
                fares = [x.get("fareDetails") or {} for x in f.get("fares") or []]
                fares = [x for x in fares if x.get("displayFare")]
                if not fares:
                    continue
                fare = min(fares, key=lambda x: x["displayFare"])
                day = datetime.strptime(parts[3], "%d%m%Y")
                dep = datetime.combine(day, datetime.strptime(det["departureTime"], "%H:%M").time())
                arr = datetime.combine(day + timedelta(days=int(det.get("arrivingInDays") or 0)),
                                       datetime.strptime(det["arrivalTime"], "%H:%M").time())
                dur = (det.get("duration") or {}).get("time") or int((arr - dep).total_seconds() // 60)
                fn = parts[2]
                seg = Segment(origin=o, destination=d, departure=dep, arrival=arr, carrier=fn[:2],
                              carrier_name=det.get("headerTextWeb"), flight_number=fn[2:], duration_min=dur)
                warn = [NOTE]
                if fare.get("slashedFare") and fare["slashedFare"] > fare["displayFare"]:
                    warn.append(f"Includes an ixigo instant discount ({fare['slashedFare']:.0f} INR before it).")
                it = Itinerary(source="ixigo", price=float(fare["displayFare"]), currency="INR",
                               slices=[Slice(segments=[seg], duration_min=max(1, int(dur)))], booking_url=url,
                               seller="ixigo", seller_kind="ota", warnings=warn)
                k = it.flight_key
                if k not in best or it.price < best[k].price:
                    best[k] = it
    return sorted(best.values(), key=lambda i: i.price)


def _fetch(o: str, d: str, dep: date, adults: int, cabin: str) -> str:
    key = f"ixigo:{o}:{d}:{dep}:{adults}:{cabin}"
    if (hit := cache.get(key, ttl=20 * 60)) is not None:
        return hit
    url = search_url(o, d, dep, adults, cabin)

    def job(page):
        got = _browser.capture(page, lambda: page.goto(url, wait_until="domcontentloaded", timeout=45000),
                               lambda u: "/flights/v2/search/stream" in u, timeout=40, settle=1)
        return [t for _, t in got]

    bodies = _browser.run(job, "ixigo", timeout=90)
    if not bodies:
        raise RuntimeError("ixigo: no search stream from the results page (blocked?)")
    text = max(bodies, key=len)
    cache.put(key, text)
    return text


def search(q: SearchQuery) -> list[Itinerary]:
    if q.return_date or not _browser.available():
        return []
    if q.max_stops is not None and q.max_stops < 0:
        return []
    out: list[Itinerary] = []
    for o in q.origins[:1]:
        for d in q.destinations[:1]:
            if o != d:
                out += parse(_fetch(o, d, q.departure, q.adults, q.cabin), q, o, d)
    return out
