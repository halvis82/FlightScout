"""Trip.com flights through the shared headless Chrome (see _browser.py).

We open Trip.com's own results page (/flights/showfarefirst?...) and capture
the FlightListSearchSSE stream that page fetches: 30 to 70 live itineraries
with Trip.com's cheapest fare for each (price per adult incl. taxes; the page
shows it rounded up to whole units). About 10 to 20 seconds per search.

Why a browser: the same endpoint answers plain HTTP clients too, but without
the page's signed headers (``token``, ``w-payload-source``) it quotes
different, higher fares than the ones Trip.com shows its visitors (checked
side by side: $212.20 on the page vs $237.60 unsigned for the same flight).
Only the page's own response matches what a person sees.

Round trips: Trip.com lists outbounds with the cheapest round trip total and
asks for the return on the next step, so round trip Itineraries carry only
the outbound and ``return_pending=True`` (like Google's round trip list).

Trip.com searches by city (LAX also returns ONT, JFK also LGA): results are
filtered to the requested airports. Unofficial: fails soft."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from urllib.parse import urlencode

from .. import cache
from ..models import Itinerary, SearchQuery, Segment, Slice
from . import _browser

log = logging.getLogger(__name__)
SITE = "https://www.trip.com"
_CLASS = {"economy": "y", "premium": "s", "business": "c", "first": "f"}
# IATA city codes Trip.com wants in ``dcity``/``acity`` where they differ from
# the airport code (it does not resolve JFK or LHR as a city).
CITY = {
    **dict.fromkeys(["JFK", "EWR", "LGA"], "NYC"), **dict.fromkeys(["LHR", "LGW", "STN", "LTN", "LCY", "SEN"], "LON"),
    **dict.fromkeys(["CDG", "ORY", "BVA"], "PAR"), **dict.fromkeys(["HND", "NRT"], "TYO"),
    **dict.fromkeys(["ORD", "MDW"], "CHI"), **dict.fromkeys(["IAD", "DCA", "BWI"], "WAS"),
    **dict.fromkeys(["MXP", "LIN", "BGY"], "MIL"), **dict.fromkeys(["FCO", "CIA"], "ROM"),
    **dict.fromkeys(["ARN", "BMA", "NYO"], "STO"), **dict.fromkeys(["ICN", "GMP"], "SEL"),
    **dict.fromkeys(["GRU", "CGH", "VCP"], "SAO"), **dict.fromkeys(["EZE", "AEP"], "BUE"),
    **dict.fromkeys(["YYZ", "YTZ"], "YTO"), "YUL": "YMQ", "IAH": "HOU", "DAL": "DFW",
    **dict.fromkeys(["PVG", "SHA"], "SHA"), **dict.fromkeys(["PEK", "PKX"], "BJS"), "SAW": "IST",
    **dict.fromkeys(["SVO", "DME", "VKO"], "MOW"), **dict.fromkeys(["KIX", "ITM"], "OSA"), "HLP": "JKT",
    "CGK": "JKT", "BER": "BER", "DMK": "BKK", "TSA": "TPE", "MIA": "MIA", "FLL": "FLL",
}
NOTE = "Sold by Trip.com (online travel agency), not the airline."
RT_NOTE = ("Trip.com round trip: the price is Trip.com's round trip total from this outbound; "
           "the return is picked on the next step.")


def available() -> bool:
    return _browser.available()


def relevant(origins: list[str], destinations: list[str]) -> bool:
    return available()


def search_url(o: str, d: str, dep: date, ret: date | None = None, adults: int = 1, cabin: str = "economy",
               currency: str = "USD") -> str:
    p = {"dcity": CITY.get(o, o).lower(), "acity": CITY.get(d, d).lower(), "dairport": o.lower(),
         "aairport": d.lower(), "ddate": dep.isoformat(), "triptype": "rt" if ret else "ow",
         "class": _CLASS.get(cabin, "y"), "quantity": adults, "searchboxarg": "t", "nonstoponly": "off",
         "locale": "en-US", "curr": currency.upper()}
    if ret:
        p["rdate"] = ret.isoformat()
    return f"{SITE}/flights/showfarefirst?{urlencode(p)}"


def _slice(journey: dict, names: dict[str, str]) -> Slice:
    segs = []
    for x in journey.get("transSectionList") or []:
        fi = x.get("flightInfo") or {}
        carrier = fi.get("airlineCode") or "??"
        num = str(fi.get("flightNo") or "").removeprefix(carrier).lstrip("0") or None
        segs.append(Segment(
            origin=x["departPoint"]["airportCode"], destination=x["arrivePoint"]["airportCode"],
            departure=datetime.fromisoformat(x["departDateTime"]), arrival=datetime.fromisoformat(x["arriveDateTime"]),
            carrier=carrier, carrier_name=names.get(carrier), flight_number=num, duration_min=x.get("duration"),
            aircraft=((fi.get("craftInfo") or {}).get("name")),
        ))
    return Slice(segments=segs, duration_min=max(1, int(journey.get("duration") or 0)))


def _price(policy: dict, adults: int) -> float | None:
    p = policy.get("price") or {}
    per = (p.get("adult") or {}).get("totalPrice")
    if per is not None:
        return round(float(per) * adults, 2)
    return float(p["totalPrice"]) if p.get("totalPrice") is not None else None


def _bags(pol: dict) -> dict | None:
    keys = {t.get("key") for t in pol.get("tagList") or []}
    if not keys:
        return None
    return {"hand": 1 if "FREE_CARRY_ON_BAGGAGE" in keys else 0, "checked": 1 if "FREE_CHECKED_BAGGAGE" in keys else 0}


def parse(data: dict, o: str, d: str, adults: int) -> list[tuple[float, Slice, dict]]:
    """FlightListSearchSSE payload -> (price for all adults, first slice, its
    cheapest policy) per itinerary between exactly ``o`` and ``d``."""
    names = {a.get("code"): a.get("name") for a in data.get("airlineList") or [] if isinstance(a, dict)}
    out = []
    for it in data.get("itineraryList") or []:
        js, pols = it.get("journeyList") or [], it.get("policies") or []
        if not js or not pols:
            continue
        pol = min(pols, key=lambda p: _price(p, adults) or 1e12)
        price = _price(pol, adults)
        sl = _slice(js[0], names)
        if price is None or not sl.segments or sl.origin != o or sl.destination != d:
            continue
        out.append((price, sl, pol))
    return out


def events(text: str) -> dict:
    """The last complete ``data:`` event of the SSE body, slimmed to what we parse."""
    evs = [ln[5:] for ln in text.split("\n") if ln.startswith("data:")]
    for raw in reversed(evs):
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        if d.get("itineraryList") is not None or d.get("basicInfo"):
            return {"basicInfo": d.get("basicInfo"), "itineraryList": d.get("itineraryList") or [],
                    "airlineList": d.get("airlineList") or []}
    return {}


def _fetch(url: str) -> dict:
    def job(page):
        for attempt in range(2):  # the very first load of a fresh Chrome sometimes never streams
            got = _browser.capture(page, lambda: page.goto(url, wait_until="commit", timeout=45000),
                                   lambda u: "/27015/FlightListSearchSSE" in u, timeout=35, settle=1.5)
            if got:
                return [b for _, b in got]
        return []

    bodies = _browser.run(job, "tripcom", timeout=120)
    for b in reversed(bodies):
        if d := events(b):
            return d
    raise RuntimeError("tripcom: no results stream from the page")


def search(q: SearchQuery) -> list[Itinerary]:
    if not available():
        return []
    cur = q.currency.upper()
    out: list[Itinerary] = []
    for o in q.origins[:2]:
        for d in q.destinations[:2]:
            if o == d:
                continue
            url = search_url(o, d, q.departure, q.return_date, q.adults, q.cabin, cur)
            key = "tripcom:" + url
            if (data := cache.get(key, ttl=20 * 60)) is None:
                data = _fetch(url)
                cache.put(key, data)
            cur_got = ((data.get("basicInfo") or {}).get("currency") or cur).upper()
            for price, sl, pol in parse(data, o, d, q.adults):
                if q.max_stops is not None and sl.stops > q.max_stops:
                    continue
                out.append(Itinerary(
                    source="tripcom", price=price, currency=cur_got, slices=[sl], booking_url=url,
                    seller="Trip.com", seller_kind="ota", baggage=_bags(pol), return_pending=bool(q.return_date),
                    warnings=[NOTE] + ([RT_NOTE] if q.return_date else []),
                ))
    return sorted(out, key=lambda i: i.price)
