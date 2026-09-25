"""Southwest (WN) direct from southwest.com through the shared real Chrome (see
_browser.py). Southwest isn't sold by OTAs and Google often shows only some of
its fares; its shopping API answers 403 to plain HTTP clients (Akamai), but
the select flight page works in headless Chrome.

We open the select-depart deeplink and capture the JSON the page fetches
(/api/air-booking/v1/air-booking/page/air/booking/shopping). One call covers
both directions of a round trip. The cheapest available fare family per
flight is used (usually Basic); totalFare includes taxes and fees, and the
page shows it rounded up to the dollar. About 4 seconds per search."""

from __future__ import annotations

import json
import logging
from datetime import date

from .. import cache
from ..models import Itinerary, SearchQuery
from . import _browser
from ._airline import combine

log = logging.getLogger(__name__)
SITE = "https://www.southwest.com"
# fare families: WGA Basic, PLU Choice, ANY Choice Preferred, BUS Choice Extra

# Southwest's network (2026). A route missing here is simply not searched.
AIRPORTS = set("""
ABQ ALB AMA ATL AUS BDL BHM BLI BNA BOI BOS BUF BUR BWI BZN CHS CLE CLT CMH COS CRP CVG DAL DCA DEN DSM DTW
ECP ELP EUG FAT FLL GEG GRR GSP HDN HNL HOU IAD IAH ICT IND ISP ITO JAN JAX KOA LAS LAX LBB LGA LGB LIH MAF
MCI MCO MDW MEM MFR MHT MIA MKE MSP MSY MTJ OAK OGG OKC OMA ONT ORD ORF PBI PDX PHL PHX PIT PNS PSP PVD
PWM RDU RIC RNO ROC RSW SAN SAT SAV SBA SDF SEA SFO SJC SJU SLC SMF SNA SRQ STL STS STT TPA TUL TUS VPS XNA
AUA BZE CUN GCM LIR MBJ NAS PUJ PVR SJD SJO
""".split())


def available() -> bool:
    return _browser.available()


def relevant(origins: list[str], destinations: list[str]) -> bool:
    return available() and bool(AIRPORTS & set(origins)) and bool(AIRPORTS & set(destinations))


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1) -> str:
    return (f"{SITE}/air/booking/select-depart.html?adultPassengersCount={adults}&adultsCount={adults}"
            f"&departureDate={dep}&departureTimeOfDay=ALL_DAY&destinationAirportCode={dest}&fareType=USD"
            f"&int=HOMEQBOMAIR&originationAirportCode={origin}&passengerType=ADULT"
            f"&returnDate={ret or ''}&returnTimeOfDay=ALL_DAY&tripType={'roundtrip' if ret else 'oneway'}"
            f"&validate=true")


def _cheapest(fp: dict) -> tuple[float, str] | None:
    best = None
    for fam, p in ((fp or {}).get("ADULT") or {}).items():
        if (p or {}).get("availabilityStatus") != "AVAILABLE":
            continue
        v = float(p["fare"]["totalFare"]["value"])
        if best is None or v < best[0]:
            best = (v, fam)
    return best


def parse(data: dict, adults: int = 1) -> list[list[dict]]:
    """shopping JSON -> one list of journeys per direction (outbound, return)."""
    bounds = []
    for prod in ((data.get("data") or {}).get("searchResults") or {}).get("airProducts") or []:
        out = []
        for x in prod.get("details") or []:
            best = _cheapest(x.get("fareProducts"))
            if not best:
                continue
            segs = [{"origin": s["originationAirportCode"], "destination": s["destinationAirportCode"],
                     "departure": s["departureDateTime"], "arrival": s["arrivalDateTime"],
                     "carrier": s.get("marketingCarrierCode") or "WN", "number": s["flightNumber"],
                     "aircraft": s.get("aircraftEquipmentType")} for s in x["segments"]]
            out.append({"segments": segs, "total": round(best[0] * adults, 2), "fare": best[1],
                        "duration": x.get("totalDuration")})
        bounds.append(out)
    return bounds


def _fetch(url: str) -> dict:
    def job(page) -> str:
        got = _browser.capture(page, lambda: page.goto(url, wait_until="commit", timeout=45000),
                               lambda u: "/air-booking/page/air/booking/shopping" in u, timeout=40)
        return got[-1][1] if got else ""

    txt = _browser.run(job, "southwest", timeout=100)
    if not txt:
        raise RuntimeError("southwest: no shopping response")
    d = json.loads(txt)
    if not d.get("success", True) and not d.get("data"):
        log.info("southwest: %s", str(d)[:200])
    return d


def search(q: SearchQuery) -> list[Itinerary]:
    if not relevant(q.origins, q.destinations):
        return []
    out: list[Itinerary] = []
    for o in [c for c in q.origins if c in AIRPORTS][:2]:
        for d in [c for c in q.destinations if c in AIRPORTS][:2]:
            if o == d:
                continue
            url = deeplink(o, d, q.departure, q.return_date, q.adults)
            key = f"southwest:{o}:{d}:{q.departure}:{q.return_date}:{q.adults}"
            if (data := cache.get(key)) is None:
                data = _fetch(url)
                cache.put(key, data)
            bounds = parse(data, q.adults)
            if not bounds or (q.return_date and len(bounds) < 2):
                continue
            out += combine(q, "southwest", "Southwest", bounds[0], bounds[1] if q.return_date else None, "USD",
                           url, {"WN": "Southwest"}, note="Southwest cheapest available fare family (usually Basic).")
    return out
