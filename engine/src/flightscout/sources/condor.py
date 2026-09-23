"""Condor (DE) direct from condor.com's own flight API (data.condor.com).
Kiwi does not sell Condor at all. Google prices Condor's own flights
correctly (FRA-JFK $619.99 and FRA-LPA $338.99, identical here, in the September 2026
audit) but misses Condor's interline tickets such as FRA to LPA via TFS on
Binter, so this source adds the airline's own all in offers.

The API wants an ``x-api-key``, but it is the public key the website ships to
every visitor in its page config ("searchApiKey"). We read it from the home
page (cached a day) and fall back to the last known value. Requests go out
with Chrome TLS (curl_cffi) since the site sits behind Akamai.

``price`` per adult already includes all taxes, fees and surcharges (the
results page says so), and round trips are priced per direction with
journeyType=ROUND_TRIP, which is cheaper than two one ways."""

from __future__ import annotations

import re
import threading
from datetime import date, datetime

from curl_cffi import requests as cr

from .. import airports, cache
from ..models import Itinerary, SearchQuery, Segment, Slice

BASE = "https://data.condor.com"
AGENCY = "86279"  # the website's own agency id for the en-us market
_TARIFFS = "LM,LC,SPO,G,GC,F"
CURRENCIES = {"USD", "EUR", "GBP", "CAD", "CHF", "BRL"}
_CABIN = {"economy": "ECONOMY", "premium": "PREMIUM", "business": "BUSINESS"}
_lock = threading.Lock()
_session: cr.Session | None = None

# Condor's own markets. Its interline partners add hundreds of airports but a
# Condor ticket always touches one of these countries.
HOME = {"DE", "AT", "CH"}


def _s() -> cr.Session:
    global _session
    with _lock:
        if _session is None:
            _session = cr.Session(impersonate="chrome")
        return _session


def _key() -> str:
    key = cache.get("condor-key", ttl=24 * 3600)
    if key:
        return key
    try:
        html = _s().get("https://www.condor.com/en-us/", timeout=30).text
        m = re.search(r'searchApiKey\\?"\s*:\s*\\?"([A-Za-z0-9]{20,})', html)
        key = m.group(1) if m else ""
    except cr.exceptions.RequestException:
        key = ""
    if not key:
        raise RuntimeError("condor: could not read the public search key from condor.com")
    cache.put("condor-key", key)
    return key


def _get(path: str, params: dict) -> list | dict:
    h = {"x-api-key": _key(), "Origin": "https://www.condor.com", "Referer": "https://www.condor.com/",
         "Accept": "application/json"}
    r = _s().get(f"{BASE}{path}", params=params, headers=h, timeout=40)
    if r.status_code == 403:  # key rotated: refetch once
        cache.put("condor-key", "")
        h["x-api-key"] = _key()
        r = _s().get(f"{BASE}{path}", params=params, headers=h, timeout=40)
    r.raise_for_status()
    return r.json()


def _served() -> set[str]:
    data = cache.get("condor-airports", ttl=24 * 3600)
    if data is None:
        data = [a["id"] for a in _get("/airports", {"journeyType": "ONE_WAY", "flightPosition": 1,
                                                     "originOrDestination": "ORIGIN"})]
        cache.put("condor-airports", data)
    return set(data)


def relevant(origins: list[str], destinations: list[str]) -> bool:
    def cc(codes):
        return {a.country for c in codes if (a := airports.get(c))}
    o, d = cc(origins), cc(destinations)
    return bool(o and d and (o | d) & HOME)


def _api_currency(cur: str) -> str:
    return cur.upper() if cur.upper() in CURRENCIES else "USD"


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1) -> str:
    """Condor's results page with the search already run (en-us market, USD)."""
    u = (f"https://www.condor.com/en-us/book/flight-search-results/?departureAirport={origin}"
         f"&destinationAirport={dest}&departureDay={dep.isoformat()}")
    if ret:
        u += f"&returnDay={ret.isoformat()}"
    return u + f"&journeyType={'ROUND_TRIP' if ret else 'ONE_WAY'}&adults={adults}"


def _minutes(iso: str) -> int:
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?", iso or "")
    if not m:
        return 0
    d, h, mi = (int(x or 0) for x in m.groups())
    return d * 1440 + h * 60 + mi


def _local(ts: str) -> datetime:
    return datetime.fromisoformat(ts).replace(tzinfo=None)


def _vacancies(origin: str, dest: str, day: date, journey: str, pos: int, cur: str, adults: int,
               cabin: str) -> list[dict]:
    """Cheapest fare per flight in the cabin, per adult."""
    key = f"condor:{origin}:{dest}:{day}:{journey}:{pos}:{cur}:{adults}:{cabin}"
    if (hit := cache.get(key)) is not None:
        return hit
    rows = _get("/flightVacancies", {
        "originIds": origin, "destinationIds": dest, "departureFrom": day.isoformat(),
        "departureTo": day.isoformat(), "journeyType": journey, "flightPosition": pos,
        "tariffIds": _TARIFFS, "agencyId": AGENCY, "paxTypes": "ADULT", "minSeats": adults,
        "currencyId": cur, "fields": "$flightDetails,$scheduleDetails",
    })
    best: dict[str, dict] = {}
    for v in rows or []:
        if v.get("compartmentId") != cabin or v.get("paxType") != "ADULT":
            continue
        price = float(v["price"])
        fid = v["flightId"]
        if fid in best and best[fid]["price"] <= price:
            continue
        best[fid] = {
            "price": price, "tariff": v.get("tariffId"), "seats": v.get("freeSeats") or 0,
            "minutes": _minutes(v.get("totalDuration")),
            "segments": [{"origin": s["originId"], "destination": s["destinationId"],
                          "departure": s["departure"], "arrival": s["arrival"], "carrier": s["carrierId"],
                          "number": s["flightNumber"]} for s in v.get("segments") or []],
        }
    out = list(best.values())
    cache.put(key, out)
    return out


def _slice(j: dict) -> Slice:
    segs = [Segment(origin=s["origin"], destination=s["destination"], departure=_local(s["departure"]),
                    arrival=_local(s["arrival"]), carrier=s["carrier"],
                    carrier_name="Condor" if s["carrier"] == "DE" else None, flight_number=s["number"])
            for s in j["segments"]]
    return Slice(segments=segs, duration_min=max(j["minutes"], 1))


def search(q: SearchQuery) -> list[Itinerary]:
    if q.cabin not in _CABIN or not relevant(q.origins, q.destinations):
        return []
    served = _served()
    cur = _api_currency(q.currency)
    cabin = _CABIN[q.cabin]
    journey = "ROUND_TRIP" if q.return_date else "ONE_WAY"
    out: list[Itinerary] = []
    for o in q.origins[:3]:
        for d in q.destinations[:3]:
            if o not in served or d not in served:
                continue
            outs = _vacancies(o, d, q.departure, journey, 1, cur, q.adults, cabin)
            backs = _vacancies(d, o, q.return_date, journey, 2, cur, q.adults, cabin) if q.return_date else [None]
            outs = sorted(outs, key=lambda x: x["price"])[:6]
            backs = sorted(backs, key=lambda x: x["price"])[:6] if q.return_date else [None]
            for a in outs:
                for b in backs:
                    if q.max_stops is not None and (len(a["segments"]) - 1 > q.max_stops
                                                    or (b and len(b["segments"]) - 1 > q.max_stops)):
                        continue
                    per_adult = a["price"] + (b["price"] if b else 0)
                    warn = []
                    if a["seats"] <= 3 or (b and b["seats"] <= 3):
                        warn.append("Only a few seats left at this Condor fare.")
                    if a["tariff"] == "LM" or (b and b["tariff"] == "LM"):
                        warn.append("Condor Economy Zero (lowest) fare: check what it includes before booking.")
                    if cur != "USD":
                        warn.append("Condor's US site shows this fare in USD, so the booking page amount can differ.")
                    out.append(Itinerary(
                        source="condor", price=round(per_adult * q.adults, 2), currency=cur,
                        slices=[_slice(a)] + ([_slice(b)] if b else []),
                        booking_url=deeplink(o, d, q.departure, q.return_date, q.adults),
                        seller="Condor", seller_kind="airline", warnings=warn,
                    ))
    return out
