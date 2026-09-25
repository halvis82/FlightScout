"""Air France / KLM (AF, KL and their partners) direct from klm.com through
the shared real Chrome (see _browser.py). Both airlines run the same booking
engine; the KLM site sells the whole AF-KLM network (KLM and Air France
flights, and connections over AMS and CDG), so one module covers both.

The site's GraphQL API (/gql/v1) needs a per request proof of work
("hashcash") computed by the page's own script, and Akamai guards it, so we
do not call it ourselves: we open the site's own deeplink (/search/offers?..)
in headless Chrome and capture the ``SearchResultAvailableOffersQuery``
response the page fetches: every itinerary with its cheapest price per cabin,
incl. taxes and surcharges, for all passengers. About 15 to 25 seconds.

Prices are in the market currency klm.com picks (USD from the US). One ways
are exact. For round trips the outbound list shows the cheapest round trip
price that includes each outbound (the return is picked on the next page), so
those itineraries are ``return_pending`` like Google's round trip rows."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime

from .. import cache
from ..models import Itinerary, SearchQuery, Segment, Slice
from . import _browser
from ._airline import countries

log = logging.getLogger(__name__)
SITE = "https://www.klm.com"
NAMES = {"KL": "KLM", "AF": "Air France", "WA": "KLM Cityhopper", "HV": "Transavia", "DL": "Delta",
         "VS": "Virgin Atlantic", "KQ": "Kenya Airways"}
HOME = {"NL", "FR"}
EUROPE = HOME | {
    "GB", "IE", "BE", "LU", "DE", "AT", "CH", "IT", "ES", "PT", "DK", "NO", "SE", "FI", "IS", "PL", "CZ",
    "SK", "HU", "SI", "HR", "RS", "BA", "ME", "AL", "MK", "GR", "CY", "MT", "RO", "BG", "LT", "LV", "EE",
    "UA", "MD", "TR", "GE", "AM",
}
_CABIN = {"economy": "ECONOMY", "premium": "PREMIUM", "business": "BUSINESS", "first": "LA_PREMIERE"}


def available() -> bool:
    return _browser.available()


def relevant(origins: list[str], destinations: list[str]) -> bool:
    """Trips touching France or the Netherlands, or long hauls between
    Europe and the rest of the world (sold over AMS or CDG)."""
    if not available():
        return False
    o, d = countries(origins), countries(destinations)
    if not (o and d):
        return False
    if HOME & (o | d):
        return True
    return bool((o & EUROPE and d - EUROPE) or (d & EUROPE and o - EUROPE))


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1,
             cabin: str = "economy") -> str:
    conns = f"{origin}:A:{dep:%Y%m%d}%3E{dest}:A"
    if ret:
        conns += f"-{dest}:A:{ret:%Y%m%d}%3E{origin}:A"
    return (f"{SITE}/search/offers?pax={adults}:0:0:0:0:0:0:0&cabinClass={_CABIN.get(cabin, 'ECONOMY')}"
            f"&activeConnection=0&connections={conns}&bookingFlow=LEISURE")


def parse(data: dict, cabin: str = "economy") -> tuple[list[dict], str | None]:
    """SearchResultAvailableOffersQuery JSON -> (journeys, currency). Each
    journey keeps its cheapest product in ``cabin`` (price for all
    passengers)."""
    want = _CABIN.get(cabin, "ECONOMY")
    ao = (data.get("data") or {}).get("availableOffers") or {}
    out, currency = [], None
    for it in ao.get("offerItineraries") or []:
        conn = it.get("activeConnection") or {}
        best = None
        for prod in it.get("upsellCabinProducts") or []:
            for c in prod.get("connections") or []:
                if c.get("cabinClass") != want or not c.get("price"):
                    continue
                p = float(c["price"]["amount"])
                if best is None or p < best[0]:
                    best = (p, c["price"]["currencyCode"], (c.get("fareFamily") or {}).get("code"),
                            c.get("numberOfSeatsAvailable"))
        if not best or not conn.get("segments"):
            continue
        segs = []
        for s in conn["segments"]:
            mf = s.get("marketingFlight") or {}
            segs.append({
                "origin": s["origin"]["code"], "destination": s["destination"]["code"],
                "departure": s["departureDateTime"], "arrival": s["arrivalDateTime"],
                "carrier": (mf.get("carrier") or {}).get("code"), "number": mf.get("number"),
                "operated_by": ((mf.get("operatingFlight") or {}).get("carrier") or {}).get("code"),
                "duration": s.get("duration"), "aircraft": s.get("equipmentName"),
            })
        out.append({"segments": segs, "total": best[0], "fare": best[2], "seats": best[3],
                    "duration": conn.get("duration")})
        currency = best[1]
    return out, currency


def _slice(j: dict) -> Slice:
    segs = [Segment(
        origin=s["origin"], destination=s["destination"],
        departure=datetime.fromisoformat(s["departure"]), arrival=datetime.fromisoformat(s["arrival"]),
        carrier=s["carrier"], carrier_name=NAMES.get(s["carrier"]), flight_number=str(s["number"]).lstrip("0") or "0",
        duration_min=s.get("duration"), aircraft=s.get("aircraft"),
    ) for s in j["segments"]]
    dur = j.get("duration") or int((segs[-1].arrival - segs[0].departure).total_seconds() // 60)
    return Slice(segments=segs, duration_min=max(dur, 1))


def _fetch(url: str) -> dict:
    def job(page) -> tuple[str, str]:
        got = _browser.capture(page, lambda: page.goto(url, wait_until="commit", timeout=45000),
                               lambda u: "operationName=SearchResultAvailableOffersQuery" in u, timeout=45)
        return (got[-1][1], "") if got else ("", page.url)

    txt, where = _browser.run(job, "afklm", timeout=150)
    if not txt:
        raise RuntimeError(f"afklm: no availability response (ended on {where[:80]})")
    d = json.loads(txt)
    if "data" not in d:
        raise RuntimeError(f"afklm: error response {txt[:150]!r}")
    return d


def search(q: SearchQuery) -> list[Itinerary]:
    if not relevant(q.origins, q.destinations):
        return []
    out: list[Itinerary] = []
    for o in q.origins[:2]:
        for d in q.destinations[:2]:
            if o == d:
                continue
            url = deeplink(o, d, q.departure, q.return_date, q.adults, q.cabin)
            key = f"afklm:{url}"
            if (data := cache.get(key)) is None:
                data = _fetch(url)
                cache.put(key, data)
            js, cur = parse(data, q.cabin)
            if q.max_stops is not None:
                js = [j for j in js if len(j["segments"]) - 1 <= q.max_stops]
            for j in sorted(js, key=lambda x: x["total"])[:12]:
                fare = j["fare"] or "lowest"
                warn = [f"Round trip from price on klm.com ({fare} fare); the return is picked on the booking page."
                        if q.return_date else f"KLM/Air France {fare} fare."]
                if j.get("seats") and j["seats"] <= 3:
                    warn.append("Only a few seats left at this fare.")
                out.append(Itinerary(
                    source="afklm", price=round(j["total"], 2), currency=cur or "USD", slices=[_slice(j)],
                    booking_url=url, seller="KLM / Air France", seller_kind="airline",
                    return_pending=bool(q.return_date), warnings=warn,
                ))
    return out
