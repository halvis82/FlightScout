"""eDreams (and Opodo, see opodo.py), the eDreams ODIGEO OTAs, through the
shared real Chrome (see _browser.py). Their search GraphQL call
(frontend-api/service/graphql, searchItinerary) only answers inside a
browser session the result page sets up, so we open the site's own results
deeplink headless and capture that JSON: every itinerary with its sections,
carriers and fees. About 15 to 40 seconds per search.

Prices: the sites show the Prime (paid membership) price first and the
regular price below it. We use the regular price (MEMBER_PRICE_POLICY_UNDISCOUNTED),
which is what a non member pays, and mention the Prime price in a warning.
Fees are per passenger, so we multiply by the number of adults. The results
include nearby airports (BCN-LHR also returns Gatwick and Stansted); we keep
the requested airports only.

The market comes from the domain: www.edreams.com prices in EUR,
www.opodo.co.uk in GBP (see BRANDS); search() converts to the query currency."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime

from .. import cache
from ..models import Itinerary, SearchQuery, Segment, Slice
from . import _browser

log = logging.getLogger(__name__)
BRANDS = {
    "edreams": ("eDreams", {"EUR": "www.edreams.com"}),
    "opodo": ("Opodo", {"GBP": "www.opodo.co.uk"}),
}
_PRIME = "MEMBER_PRICE_POLICY_DISCOUNTED"
_REGULAR = "MEMBER_PRICE_POLICY_UNDISCOUNTED"


def available() -> bool:
    return _browser.available()


def relevant(origins: list[str], destinations: list[str]) -> bool:
    return available()  # global OTAs


def domain(brand: str, currency: str) -> str:
    doms = BRANDS[brand][1]
    return doms.get(currency.upper(), next(iter(doms.values())))


def deeplink(host: str, origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1) -> str:
    h = f"type={'R' if ret else 'O'};dep={dep.isoformat()};"
    if ret:
        h += f"ret={ret.isoformat()};"
    h += f"from={origin};to={dest};adults={adults};collectionmethod=false;airlinescodes=false;internalSearch=true"
    return f"https://{host}/travel/#results/{h}"


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=None)


def _slice(leg: dict, segs: dict, secs: dict, locs: dict, carriers: dict) -> Slice | None:
    seg = segs.get(leg["segmentId"])
    if not seg:
        return None
    out = []
    for sid in seg["sections"]:
        s = secs[sid]
        if s.get("transportType") not in (None, "PLANE"):  # train or bus legs
            return None
        carrier = s.get("carrierId") or "??"
        out.append(Segment(
            origin=locs[s["departureId"]]["iata"], destination=locs[s["destinationId"]]["iata"],
            departure=_dt(s["departureDate"]), arrival=_dt(s["arrivalDate"]), carrier=carrier,
            carrier_name=carriers.get(carrier),
            flight_number=str(s.get("flightCode") or "").removeprefix(carrier) or None,
            duration_min=s.get("duration"), aircraft=s.get("vehicleModel")))
    return Slice(segments=out, duration_min=max(1, seg.get("duration") or 1)) if out else None


def parse(data: dict, brand: str, adults: int = 1, url: str = "") -> list[Itinerary]:
    """searchItinerary JSON -> Itineraries (all airports, unfiltered)."""
    d = (data.get("data") or {}).get("searchItinerary") or {}
    name = BRANDS[brand][0]
    secs = {s["id"]: s["section"] for s in d.get("sections") or []}
    segs = {s["id"]: s["segment"] for s in d.get("segments") or []}
    locs = {x["id"]: x["location"] for x in d.get("locations") or []}
    carriers = {c["id"]: c["carrier"].get("name") for c in d.get("carriers") or []}
    out = []
    for it in d.get("itineraries") or []:
        fees = {f["type"]: f["price"] for f in it.get("fees") or []}
        reg = fees.get(_REGULAR) or next(iter(fees.values()), None)
        if not reg:
            continue
        slices = [sl for leg in it.get("legs") or [] if (sl := _slice(leg, segs, secs, locs, carriers))]
        if not slices or len(slices) != len(it.get("legs") or []):
            continue
        warn = [f"Sold by {name} (online travel agency), not the airline."]
        if (p := fees.get(_PRIME)) and p["amount"] < reg["amount"]:
            warn.append(f"{name} Prime members (paid subscription) pay {p['currency']} "
                        f"{p['amount'] * adults:.2f}. This is the regular price.")
        if 0 < (it.get("ticketsLeft") or 0) <= 3:
            warn.append(f"Only {it['ticketsLeft']} seats left at this {name} price.")
        multi = any(len({s.carrier for s in sl.segments}) > 1 for sl in slices)
        out.append(Itinerary(
            source=brand, price=round(reg["amount"] * adults, 2), currency=reg["currency"], slices=slices,
            booking_url=url, seller=name, seller_kind="ota", self_transfer=False,
            warnings=warn + (["Mixed airlines: may be separate tickets combined by the OTA."] if multi else []),
        ))
    return out


def _fetch(brand: str, url: str) -> dict:
    def job(page) -> str:
        page.goto("about:blank")  # the query sits in the #hash: force a real load
        got = _browser.capture(page, lambda: page.goto(url, wait_until="commit", timeout=45000),
                               lambda u: "/frontend-api/service/graphql" in u, timeout=75,
                               body=lambda t: '"searchItinerary"' in t[:200])
        return got[-1][1] if got else ""

    txt = _browser.run(job, brand, timeout=150)
    if not txt:
        raise RuntimeError(f"{brand}: no search response")
    d = json.loads(txt)
    if not (d.get("data") or {}).get("searchItinerary"):
        raise RuntimeError(f"{brand}: error response {txt[:150]!r}")
    return d


def search_brand(q: SearchQuery, brand: str) -> list[Itinerary]:
    if not available():
        return []
    host = domain(brand, q.currency)
    out: list[Itinerary] = []
    for o in q.origins[:1]:
        for d in q.destinations[:1]:
            if o == d:
                continue
            url = deeplink(host, o, d, q.departure, q.return_date, q.adults)
            key = f"edreams:{url}"
            if (data := cache.get(key, ttl=1800)) is None:
                data = _fetch(brand, url)
                cache.put(key, data)
            want = [(o, d)] + ([(d, o)] if q.return_date else [])
            for it in parse(data, brand, q.adults, url):
                if [(sl.origin, sl.destination) for sl in it.slices] != want:
                    continue
                if q.max_stops is not None and any(sl.stops > q.max_stops for sl in it.slices):
                    continue
                out.append(it)
    return sorted(out, key=lambda i: i.price)


def search(q: SearchQuery) -> list[Itinerary]:
    return search_brand(q, "edreams")
