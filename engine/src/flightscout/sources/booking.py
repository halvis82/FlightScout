"""Booking.com Flights (flights.booking.com, fares and ticketing by Etraveli,
the Gotogate / Mytrip group) through the JSON endpoint its own results page
calls: /api/flights/ (keyless, Chrome TLS impersonation, plain HTTP).

One GET returns 15 live offers for a page of results with the full price
breakdown (total for all passengers incl. taxes and Booking's fees, exactly
the number the results page shows, rounded there to whole units), every leg
with its flight number and UTC offsets, and included baggage. We ask for the
cheapest page and the "best" page (2 requests per route), 0.5 to 15 seconds
each. The market follows the ``currency`` parameter (USD, EUR, NOK, ...).

Unofficial: the schema can change without notice; everything fails soft."""

from __future__ import annotations

import threading
import time
from datetime import date, datetime
from urllib.parse import urlencode

from curl_cffi import requests as cr

from .. import cache
from ..models import Itinerary, SearchQuery, Segment, Slice

SITE = "https://flights.booking.com"
API = SITE + "/api/flights/"
_CABIN = {"economy": "ECONOMY", "premium": "PREMIUM_ECONOMY", "business": "BUSINESS", "first": "FIRST"}
_local = threading.local()
NOTE = "Sold by Booking.com Flights (ticketing by Etraveli / Gotogate), not the airline."
VI_NOTE = ("Separate tickets on different airlines combined by Booking.com (virtual interlining), "
           "protected by the agency, not by the airlines; you may need to collect and recheck bags.")


def relevant(origins: list[str], destinations: list[str]) -> bool:
    return True  # every market Booking.com sells


def _session() -> cr.Session:
    if not hasattr(_local, "s"):
        _local.s = cr.Session(impersonate="chrome")
    return _local.s


def _params(o: str, d: str, dep: date, ret: date | None, adults: int, cabin: str, currency: str,
            sort: str = "CHEAPEST") -> dict:
    p = {"type": "ROUNDTRIP" if ret else "ONEWAY", "adults": str(adults), "cabinClass": _CABIN.get(cabin, "ECONOMY"),
         "children": "", "from": f"{o}.AIRPORT", "to": f"{d}.AIRPORT", "depart": dep.isoformat(), "sort": sort,
         "currency": currency.upper(), "enableVI": "1"}  # the page asks with enableVI=1 (self transfer deals)
    if ret:
        p["return"] = ret.isoformat()
    return p


def search_url(o: str, d: str, dep: date, ret: date | None = None, adults: int = 1, cabin: str = "economy",
               currency: str = "USD", token: str | None = None) -> str:
    """The results page, or with ``token`` the page of that one offer."""
    p = _params(o, d, dep, ret, adults, cabin, currency)
    path = f"/flights/{o}.AIRPORT-{d}.AIRPORT/" + (f"{token}/" if token else "")
    return SITE + path + "?" + urlencode(p)


def _money(m: dict | None) -> float | None:
    if not m or m.get("units") is None:
        return None
    return round(float(m["units"]) + float(m.get("nanos") or 0) / 1e9, 2)


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _slice(seg: dict) -> Slice:
    out = []
    for leg in seg.get("legs") or []:
        fi = leg.get("flightInfo") or {}
        ci = fi.get("carrierInfo") or {}
        carrier = ci.get("marketingCarrier") or (leg.get("carriers") or ["??"])[0]
        names = {c.get("code"): c.get("name") for c in leg.get("carriersData") or []}
        dur = None
        if leg.get("departureTimeTz") and leg.get("arrivalTimeTz"):
            dur = int((_dt(leg["arrivalTimeTz"]) - _dt(leg["departureTimeTz"])).total_seconds() // 60)
        elif leg.get("totalTime"):
            dur = int(leg["totalTime"]) // 60
        out.append(Segment(
            origin=leg["departureAirport"]["code"], destination=leg["arrivalAirport"]["code"],
            departure=_dt(leg["departureTime"]), arrival=_dt(leg["arrivalTime"]),
            carrier=carrier, carrier_name=names.get(carrier), flight_number=str(fi.get("flightNumber") or "") or None,
            duration_min=dur, aircraft=fi.get("planeType") or None,
        ))
    total = int(seg.get("totalTime") or 0) // 60
    if not total and out:
        total = int((out[-1].arrival - out[0].departure).total_seconds() // 60)
    return Slice(segments=out, duration_min=max(total, 1))


def _bags(offer: dict) -> dict | None:
    segs = offer.get("segments") or []
    if not segs:
        return None
    first = segs[0]
    checked = sum((x.get("luggageAllowance") or {}).get("maxPiece") or 0
                  for x in first.get("travellerCheckedLuggage") or [] if x.get("travellerReference") == "1")
    hand = [(x.get("luggageAllowance") or {}).get("luggageType") for x in first.get("travellerCabinLuggage") or []
            if x.get("travellerReference") == "1"]
    return {"checked": checked, "hand": len(hand), "hand_types": hand}


def parse(data: dict, q: SearchQuery, o: str, d: str) -> list[Itinerary]:
    """/api/flights/ JSON -> Itineraries between exactly ``o`` and ``d``."""
    out = []
    for off in data.get("flightOffers") or []:
        price = _money((off.get("priceBreakdown") or {}).get("total"))
        cur = ((off.get("priceBreakdown") or {}).get("total") or {}).get("currencyCode")
        segs = off.get("segments") or []
        if price is None or not segs or not all(s.get("legs") for s in segs):
            continue
        slices = [_slice(s) for s in segs]
        if slices[0].origin != o or slices[0].destination != d:
            continue
        if q.max_stops is not None and any(s.stops > q.max_stops for s in slices):
            continue
        vi = any(s.get("isVirtualInterlining") for s in segs)
        warn = [NOTE] + ([VI_NOTE] if vi else [])
        out.append(Itinerary(
            source="booking", price=price, currency=cur or q.currency.upper(), slices=slices,
            booking_url=search_url(o, d, q.departure, q.return_date, q.adults, q.cabin, cur or q.currency,
                                   token=off.get("token")),
            seller="Booking.com", seller_kind="ota", baggage=_bags(off), self_transfer=vi, warnings=warn,
        ))
    return out


def _fetch(params: dict) -> dict:
    key = "booking:" + urlencode(sorted(params.items()))
    if (hit := cache.get(key, ttl=20 * 60)) is not None:
        return hit
    last = ""
    for attempt in range(2):
        r = _session().get(API, params=params, timeout=45, headers={
            "Accept": "application/json", "Referer": f"{SITE}/flights/{params['from']}-{params['to']}/"})
        if r.status_code in (429, 500, 502, 503, 504):
            last = f"HTTP {r.status_code}"
            time.sleep(1.5)
            continue
        if r.status_code != 200 or "json" not in r.headers.get("content-type", ""):
            raise RuntimeError(f"booking: HTTP {r.status_code} {r.text[:120]!r}")
        d = r.json()
        if d.get("error") or ("flightOffers" not in d and d.get("code")):
            raise RuntimeError(f"booking: {str(d)[:200]}")
        cache.put(key, d)
        return d
    raise RuntimeError(f"booking: no response ({last})")


def search(q: SearchQuery) -> list[Itinerary]:
    out: dict[str, Itinerary] = {}
    for o in q.origins[:2]:
        for d in q.destinations[:2]:
            if o == d:
                continue
            for sort in ("CHEAPEST", "BEST"):
                p = _params(o, d, q.departure, q.return_date, q.adults, q.cabin, q.currency, sort)
                if q.max_stops == 0:
                    p["stops"] = "0"
                for it in parse(_fetch(p), q, o, d):
                    k = it.flight_key
                    if k not in out or it.price < out[k].price:
                        out[k] = it
    return sorted(out.values(), key=lambda i: i.price)
