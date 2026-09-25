"""WestJet (WS) direct from westjet.com through the shared real Chrome (see
_browser.py). WestJet's shopping API (apiw.westjet.com/ecomm/booktrip/
flight-search-api/v1) is guarded by a bot manager that signs every request
from its own page script, so plain HTTP clients get 429; headless Chrome on
a westjet.com page passes.

Flow: open westjet.com once per session, then post the same search the
select flight page posts, from inside the page (the bot manager's script
adds its headers). One call per direction; for a round trip the page asks
with both trips and ``currentFlightIndex`` 1 then 2, and so do we (the
return prices then match the round trip flow, which can differ by a few
dollars from a one way search). Prices are per person in CAD incl. taxes
and fees ("From" on the page, Basic or Econo); premium cabin searches use
the cheapest Premium fare. About 3 to 4 seconds per direction once warm
(about 12 seconds for the first search).

Airports: data/westjet_airports.json, the site's own destination list
(incl. partner airports it sells); we only ask WestJet when one end is in
Canada."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date
from functools import cache as memo
from pathlib import Path

from .. import airports, cache
from ..models import Itinerary, SearchQuery
from . import _browser
from ._airline import combine

log = logging.getLogger(__name__)
SITE = "https://www.westjet.com"
API = "https://apiw.westjet.com/ecomm/booktrip/flight-search-api/v1"

_JS = """async (b) => {
  const r = await fetch('%s', {method: 'POST', body: JSON.stringify(b),
    headers: {'Content-Type': 'application/json', 'Accept': 'application/json, text/plain, */*'}});
  return [r.status, await r.text()];
}""" % API


@memo
def stations() -> set[str]:
    return set(json.loads((Path(__file__).parents[1] / "data" / "westjet_airports.json").read_text()))


def available() -> bool:
    return _browser.available()


def _pairs(origins: list[str], destinations: list[str]) -> list[tuple[str, str]]:
    st = stations()

    def ca(c):
        return (a := airports.get(c)) is not None and a.country == "CA"
    return [(o, d) for o in origins for d in destinations
            if o in st and d in st and o != d and (ca(o) or ca(d))]


def relevant(origins: list[str], destinations: list[str]) -> bool:
    return bool(_pairs(origins, destinations)) and available()


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1) -> str:
    return (f"{SITE}/booking/Create.html?lang=en&type=search&origin={origin}&destination={dest}"
            f"&adults={adults}&children=0&infants=0&outboundDate={dep}&returnDate={ret or ''}"
            f"&companionvoucher=false&iopvoucher=false&currency=CAD")


def _body(trips: list[tuple[str, str, date]], index: int, adults: int, book_id: str) -> dict:
    return {"appSource": "unknown", "bookId": book_id, "isBereavement": False, "isCompanion": False,
            "currency": "CAD", "currentFlightIndex": index,
            "guests": [{"type": "adult", "count": str(adults)}, {"type": "child", "count": "0"},
                       {"type": "infant", "count": "0"}],
            "showMemberExclusives": False, "showTravelPrivileges": False,
            "trips": [{"arrival": d, "calLowestPrice": "", "departure": o, "departureDate": str(day), "order": i + 1}
                      for i, (o, d, day) in enumerate(trips)],
            "isCommissionable": False, "promoCode": ""}


def parse(data: dict, adults: int = 1, cabin: str = "economy") -> list[dict]:
    """flight-search-api JSON (one direction) -> journeys."""
    premium = cabin != "economy"
    out = []
    for f in data.get("flights") or []:
        for o in f.get("flightOptions") or []:
            fare = o.get("adultFare") or {}
            prices = []
            for p in fare.get("priceDetails") or []:
                is_prem = "W" in (p.get("cabinCodes") or []) or "Premium" in (p.get("fareType") or "")
                if is_prem == premium and p.get("totalFareAmount"):
                    prices.append((float(p["totalFareAmount"]), p.get("fareType")))
            if not prices:
                continue
            price, fam = min(prices)
            det = o.get("flightDetails") or {}
            segs = [{"origin": s["originCode"], "destination": s["destinationCode"],
                     "departure": s["departureDateRaw"][:19], "arrival": s["arrivalDateRaw"][:19],
                     "carrier": s.get("marketingAirline") or "WS", "number": s["flightNumber"],
                     "aircraft": s.get("equipmentCode"),
                     "duration": (s["totalFlightDuration"]["hrs"] * 60 + s["totalFlightDuration"]["mins"])
                     if s.get("totalFlightDuration") else None}
                    for s in det.get("flightSegments") or []]
            if not segs:
                continue
            tt = det.get("totalTravelDuration") or {}
            out.append({"segments": segs, "total": round(price * adults, 2), "fare": fam,
                        "duration": tt["hrs"] * 60 + tt["mins"] if tt else None})
    return out


def _fetch(bodies: list[dict]) -> list[dict]:
    def job(page) -> list[str]:
        if "westjet.com" not in page.url:  # new session: let the bot manager script load
            page.goto(SITE + "/en-ca", wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(3000)
        res = []
        for b in bodies:
            status, txt = page.evaluate(_JS, b)
            if status != 200:
                raise RuntimeError(f"westjet: search answered {status}")
            res.append(txt)
        return res

    return [json.loads(t) for t in _browser.run(job, "westjet", timeout=120)]


def search(q: SearchQuery) -> list[Itinerary]:
    pairs = _pairs(q.origins, q.destinations)
    if not pairs or not available() or q.cabin == "first":
        return []
    out: list[Itinerary] = []
    for o, d in pairs[:2]:
        key = f"westjet:{o}:{d}:{q.departure}:{q.return_date}:{q.adults}"
        if (data := cache.get(key)) is None:
            bid = str(uuid.uuid4())
            trips = [(o, d, q.departure)] + ([(d, o, q.return_date)] if q.return_date else [])
            data = _fetch([_body(trips, i + 1, q.adults, bid) for i in range(len(trips))])
            cache.put(key, data)
        outs = parse(data[0], q.adults, q.cabin)
        backs = parse(data[1], q.adults, q.cabin) if q.return_date and len(data) > 1 else None
        if q.return_date and not backs:
            continue
        out += combine(q, "westjet", "WestJet", outs, backs, "CAD", deeplink(o, d, q.departure, q.return_date, q.adults),
                       {"WS": "WestJet"}, note="WestJet cheapest fare (Basic when offered) incl. taxes; bags extra.")
    return out
