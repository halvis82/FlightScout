"""Breeze Airways (MX) direct from flybreeze.com's own GraphQL backend
(api.flybreeze.com, a layer over Navitaire dotREZ). Breeze sells mostly on
its own site and Google often lacks its fares, so this fills a real gap.

No key: an anonymous dotREZ token comes from POST
/digital-api/external/api/auth/v1/token/anonymous and goes into the query
variables. The ``simpleAvailability`` query is the one the results page runs
(same criteria). Plain HTTP with Chrome TLS impersonation (curl_cffi); one
request covers both directions of a round trip, about 1 second.

Price per journey = sum of its per segment fare amounts (a connection is
priced per segment), incl. taxes and fees: the "No Flex Fare" (Nice) price
the page shows, rounded there to the dollar. Bundles (Nicer, Nicest) are
extra. Routes come from data/breeze_routes.json (the site's own
``primaryResources.markets``, connections included)."""

from __future__ import annotations

import json
import threading
import time
from datetime import date
from functools import cache as memo
from pathlib import Path
from urllib.parse import quote

from curl_cffi import requests as cr

from .. import cache
from ..models import Itinerary, SearchQuery
from ._airline import combine

API = "https://api.flybreeze.com"
SITE = "https://www.flybreeze.com"
_HEADERS = {"Origin": SITE, "Referer": SITE + "/", "Accept": "application/json, text/plain, */*",
            "content-type": "application/json"}
_lock = threading.Lock()
_session: cr.Session | None = None
_token: tuple[str, float] | None = None

_QUERY = """query SimpleAvailability($searchCriteria: SimpleAvailabilityRequest!, $dotrezToken: String,
  $useEss: Boolean, $initialBooking: Boolean) {
  simpleAvailability(searchCriteria: $searchCriteria, dotrezToken: $dotrezToken, useEss: $useEss,
    initialBooking: $initialBooking) {
    availability {
      currencyCode
      faresAvailable { fareKey fareInfo { fareAvailabilityKey fares { productClass fareBasisCode
        passengerFares { fareAmount passengerType } } } }
      results { trips { date journeysAvailableByMarket { journey {
        designator { arrival departure destination origin }
        fares { details { availableCount status } fareAvailabilityKey }
        segments { designator { arrival departure destination origin } identifier { carrierCode identifier }
          legs { legInfo { arrivalTimeUtc departureTimeUtc equipmentType } } }
        stops } } } }
    }
    errorCode
    errorMessage
  }
}"""


@memo
def routes() -> dict[str, set[str]]:
    raw = json.loads((Path(__file__).parents[1] / "data" / "breeze_routes.json").read_text())
    return {o: set(ds) for o, ds in raw.items()}


def _pairs(origins: list[str], destinations: list[str]) -> list[tuple[str, str]]:
    r = routes()
    return [(o, d) for o in origins for d in destinations if o != d and d in r.get(o, ())]


def relevant(origins: list[str], destinations: list[str]) -> bool:
    return bool(_pairs(origins, destinations))


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1) -> str:
    pax = quote(json.dumps({"types": [{"type": "ADT", "count": adults}]}, separators=(",", ":")))
    return (f"{SITE}/booking/availability?origin={origin}&destination={dest}&beginDate={dep}"
            + (f"&endDate={ret}" if ret else "") + f"&passengers={pax}")


def _post(path: str, body: dict) -> dict:
    r = _session.post(f"{API}{path}", json=body, headers=_HEADERS, timeout=40)
    r.raise_for_status()
    return r.json()


def _dotrez() -> str:
    global _session, _token
    with _lock:
        if _session is None:
            _session = cr.Session(impersonate="chrome")
        if not _token or time.time() - _token[1] > 8 * 60:
            d = _post("/digital-api/external/api/auth/v1/token/anonymous", {})
            _token = (d["data"]["token"], time.time())
        return _token[0]


def parse(data: dict, adults: int = 1) -> tuple[list[dict], list[dict]]:
    """simpleAvailability response -> (outbound, return) journeys, cheapest
    fare family per journey (No Flex Fare)."""
    sa = ((data.get("data") or {}).get("simpleAvailability")) or {}
    av = sa.get("availability") or {}
    fares = {f["fareKey"]: f["fareInfo"] for f in av.get("faresAvailable") or []}
    trips = [t for r in av.get("results") or [] for t in r.get("trips") or []]
    bounds: list[list[dict]] = []
    for t in trips:
        out = []
        for j in ((t.get("journeysAvailableByMarket") or {}).get("journey")) or []:
            best = None
            for f in j.get("fares") or []:
                info = fares.get(f["fareAvailabilityKey"])
                if not info or not any((x.get("availableCount") or 0) > 0 for x in f.get("details") or []):
                    continue
                total = sum(pf["fareAmount"] for x in info["fares"] for pf in x["passengerFares"]
                            if pf.get("passengerType") == "ADT")
                seats = min((x.get("availableCount") or 0) for x in f.get("details") or [])
                if best is None or total < best[0]:
                    best = (total, seats)
            if not best:
                continue
            segs = []
            for s in j["segments"]:
                legs = s.get("legs") or []
                dep_utc = legs[0]["legInfo"]["departureTimeUtc"] if legs else None
                arr_utc = legs[-1]["legInfo"]["arrivalTimeUtc"] if legs else None
                segs.append({"origin": s["designator"]["origin"], "destination": s["designator"]["destination"],
                             "departure": s["designator"]["departure"], "arrival": s["designator"]["arrival"],
                             "carrier": s["identifier"]["carrierCode"], "number": s["identifier"]["identifier"],
                             "dep_utc": dep_utc, "arr_utc": arr_utc})
            dur = None
            if segs[0]["dep_utc"] and segs[-1]["arr_utc"]:
                from datetime import datetime
                a = datetime.fromisoformat(segs[0]["dep_utc"].replace("Z", "+00:00"))
                b = datetime.fromisoformat(segs[-1]["arr_utc"].replace("Z", "+00:00"))
                dur = int((b - a).total_seconds() // 60)
            out.append({"segments": segs, "total": round(best[0] * adults, 2), "seats": best[1], "duration": dur})
        bounds.append(out)
    outs = bounds[0] if bounds else []
    backs = bounds[1] if len(bounds) > 1 else []
    return outs, backs


def _fetch(o: str, d: str, dep: date, ret: date | None, adults: int) -> dict:
    tok = _dotrez()
    crit = {"filters": {"bundleControlFilter": "ReturnBundleOffers", "maxConnections": 9, "loyalty": "MonetaryOnly", "compressionType": "CompressByProductClass"},
            "passengers": {"types": [{"type": "ADT", "count": adults}], "residentCountry": "US"},
            "origin": o, "destination": d, "beginDate": dep.isoformat(),
            "searchDestinationMacs": False, "searchOriginMacs": False, "numberOfFaresPerJourney": 3,
            "ssrCollectionsMode": "Leg", "taxesAndFees": "Taxes", "codes": {}}
    if ret:
        crit["endDate"] = ret.isoformat()
    data = _post("/availability/graph/public/simpleAvailability", {
        "operationName": "SimpleAvailability", "query": _QUERY,
        "variables": {"searchCriteria": crit, "dotrezToken": tok, "useEss": True, "initialBooking": False}})
    sa = (data.get("data") or {}).get("simpleAvailability") or {}
    if sa.get("errorCode") and not sa.get("availability"):
        raise RuntimeError(f"breeze: {sa.get('errorCode')} {sa.get('errorMessage')}")
    return data


def search(q: SearchQuery) -> list[Itinerary]:
    pairs = _pairs(q.origins, q.destinations)
    if not pairs or q.cabin != "economy":
        return []
    out: list[Itinerary] = []
    for o, d in pairs[:3]:
        key = f"breeze:{o}:{d}:{q.departure}:{q.return_date}:{q.adults}"
        if (data := cache.get(key)) is None:
            data = _fetch(o, d, q.departure, q.return_date, q.adults)
            cache.put(key, data)
        outs, backs = parse(data, q.adults)
        if q.return_date and not backs:
            continue
        out += combine(q, "breeze", "Breeze Airways", outs, backs if q.return_date else None, "USD",
                       deeplink(o, d, q.departure, q.return_date, q.adults), {"MX": "Breeze Airways"},
                       note="Breeze No Flex Fare incl. taxes and fees; bags and seats extra.")
    return out
