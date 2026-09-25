"""TAP Air Portugal (TP, and Portugália NI) direct from booking.flytap.com
through the shared real Chrome (see _browser.py). The booking API itself
(/bfm/rest/booking/availability/search) answers plain HTTP clients with a 403
from Cloudflare, but headless Chrome gets through.

We open the site's own deeplink (/booking/flights/deeplink?...) and capture
the availability JSON the booking app fetches: every flight plus the priced
offers (fare family x flights, totalPrice for all passengers incl. taxes, the
"Economy 104,30 EUR" of the flight page). Round trips are priced by TAP per
outbound+return pair, so we keep TAP's pair prices instead of adding two one
ways. The page lists every outbound but only the inbound(s) TAP offers with
them before one is picked (often just one), so round trips are those pairs.
About 7 to 20 seconds per search, headless."""

from __future__ import annotations

import json
import logging
from datetime import date

from .. import airports, cache
from ..models import Itinerary, SearchQuery
from . import _browser
from ._airline import make_slice

log = logging.getLogger(__name__)
SITE = "https://booking.flytap.com"
NAMES = {"TP": "TAP Air Portugal", "NI": "Portugália"}
EUROPE = {
    "PT", "ES", "FR", "GB", "IE", "BE", "NL", "LU", "DE", "CH", "AT", "IT", "DK", "SE", "NO", "FI", "PL", "CZ",
    "HU", "RO", "BG", "GR", "HR", "IS", "MT", "CY",
}
# Where TAP's Lisbon hub is the natural connection: the Americas and
# Portuguese speaking / West Africa.
LONGHAUL = {"BR", "US", "CA", "VE", "CO", "MX", "PA", "DO", "CU", "CV", "AO", "MZ", "GW", "ST", "SN", "GH", "MA",
            "TN", "DZ", "IL", "TR", "GN", "GM", "CI", "TG", "NG"}
# TAP's cabin codes: Y economy on short haul, M economy on long haul, W
# premium economy, C business.
_CABIN = {"economy": {"Y", "M"}, "premium": {"W"}, "business": {"C"}, "first": {"C"}}


def available() -> bool:
    return _browser.available()


def relevant(origins: list[str], destinations: list[str]) -> bool:
    if not available():
        return False
    o = {a.country for c in origins if (a := airports.get(c))}
    d = {a.country for c in destinations if (a := airports.get(c))}
    if not o or not d:
        return False
    if "PT" in o | d:
        return True
    return bool((o & EUROPE and d & LONGHAUL) or (d & EUROPE and o & LONGHAUL))


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1, market: str = "PT") -> str:
    q = (f"market={market}&language=EN&origin={origin}&destination={dest}&depDate={dep:%d.%m.%Y}"
         f"&flightType={'return' if ret else 'single'}")
    if ret:
        q += f"&retDate={ret:%d.%m.%Y}"
    return f"{SITE}/booking/flights/deeplink?{q}&adt={adults}&chd=0&inf=0&yth=0"


def _journey(f: dict) -> dict:
    segs = [{
        "origin": s["departureAirport"], "destination": s["arrivalAirport"],
        # local wall clock times with a bogus "Z"
        "departure": s["departureDate"].replace(".000Z", "").rstrip("Z"),
        "arrival": s["arrivalDate"].replace(".000Z", "").rstrip("Z"),
        "carrier": s.get("operationCarrier") or s["carrier"], "number": s["flightNumber"],
        "duration": s.get("duration"), "aircraft": s.get("equipment"),
    } for s in f["listSegment"]]
    return {"segments": segs, "duration": f.get("duration")}


def parse(data: dict, cabin: str = "economy") -> tuple[list[dict], str]:
    """Availability JSON -> (offers, currency). Each offer is
    ``{"out": journey, "back": journey | None, "total", "fare", "seats"}``,
    the cheapest priced fare family per flight (pair) in the cabin."""
    d = data.get("data") or {}
    offers = d.get("offers") or {}
    cur = offers.get("currency") or "EUR"
    outs = {f["idFlight"]: f for f in d.get("listOutbound") or []}
    ins = {f["idFlight"]: f for f in d.get("listInbound") or []}
    want = _CABIN.get(cabin, {"Y", "M"})
    best: dict[tuple, tuple] = {}
    for o in offers.get("listOffers") or []:
        if o.get("outCabin") not in want or (o.get("inCabin") is not None and o.get("inCabin") not in want):
            continue
        p = (o.get("totalPrice") or {}).get("price")
        if p is None:
            continue
        for g in o.get("groupFlights") or []:
            k = (g.get("idOutBound"), g.get("idInBound"))
            if k[0] not in outs or (k[1] is not None and k[1] not in ins):
                continue
            seats = min(x for x in (g.get("seatOutBound"), g.get("seatInBound")) if x is not None) \
                if g.get("seatOutBound") is not None else None
            if k not in best or p < best[k][0]:
                best[k] = (p, o.get("outFareFamily"), seats)
    res = []
    for (fo, fi), (p, ff, seats) in best.items():
        res.append({"out": _journey(outs[fo]), "back": _journey(ins[fi]) if fi is not None else None,
                    "total": round(p, 2), "fare": ff, "seats": seats})
    return sorted(res, key=lambda x: x["total"]), cur


def _fetch(url: str) -> dict:
    def job(page) -> str:
        got = _browser.capture(page, lambda: page.goto(url, wait_until="commit", timeout=60000),
                               lambda u: "/bfm/rest/booking/availability/search" in u, timeout=60)
        return got[-1][1] if got else ""

    txt = _browser.run(job, "tap", timeout=150)
    if not txt:
        raise RuntimeError("tap: no availability response (Cloudflare challenge not passed?)")
    return json.loads(txt)


def search(q: SearchQuery) -> list[Itinerary]:
    if not relevant(q.origins, q.destinations):
        return []
    out: list[Itinerary] = []
    for o in q.origins[:2]:
        for d in q.destinations[:2]:
            if o == d:
                continue
            url = deeplink(o, d, q.departure, q.return_date, q.adults)
            key = f"tap:{url}"
            if (data := cache.get(key)) is None:
                data = _fetch(url)
                cache.put(key, data)
            offers, cur = parse(data, q.cabin)
            if q.return_date:
                offers = [x for x in offers if x["back"]]
            if q.max_stops is not None:
                offers = [x for x in offers if all(len(j["segments"]) - 1 <= q.max_stops
                                                   for j in (x["out"], x["back"]) if j)]
            for x in offers[:25]:
                warn = [f"TAP {x['fare'] or 'cheapest'} fare (cheapest family of the cabin)."]
                if x["seats"] and x["seats"] <= 3:
                    warn.insert(0, "Only a few seats left at this TAP fare.")
                out.append(Itinerary(
                    source="tap", price=x["total"], currency=cur,
                    slices=[make_slice(x["out"], NAMES)] + ([make_slice(x["back"], NAMES)] if x["back"] else []),
                    booking_url=url, seller="TAP Air Portugal", seller_kind="airline", warnings=warn,
                ))
    return out
