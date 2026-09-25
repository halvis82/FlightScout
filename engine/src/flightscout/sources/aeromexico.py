"""Aeromexico (AM) direct from aeromexico.com's own booking backend
(amx-c-bkngbk-pd.aeromexico.com /bc/ow|rt/search/flight), the calls its
select flight page makes. Plain HTTP with Chrome TLS impersonation works.

No key: the site sends a fixed public client header ("Atmosphere ...
signature_method=NONE") plus two values it looks up first, and so do we:
the point of sale's ``jipcc`` (/tc/pcc/getPccInfo, sent as ``citycode``)
and the route's ``subRegionFinal`` (/tc/region/regionByRoute, sent as
``legregion``). We shop the US storefront, so fares are in USD, exactly what
aeromexico.com/en-us shows.

``fares[].currency.total`` is per passenger incl. taxes and the Mexican TUA.
Economy uses the cheapest Main or AM Plus fare (AM Plus is sometimes the
cheaper one); business uses Premier. A round trip is one rt search: each
direction is priced on its own and the two halves must share a fare type
(Basic with Basic, Classic with Classic...; the response's
``combinabilityRulesNewBranded``), which is what the page lets you pick."""

from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import date
from functools import cache as memo
from pathlib import Path

from curl_cffi import requests as cr

from .. import airports, cache
from ..models import Itinerary, SearchQuery
from ._airline import combine

SITE = "https://www.aeromexico.com"
BOOK = "https://amx-c-bkngbk-pd.aeromexico.com"
META = "https://amx-c-mtpsbk-pd.aeromexico.com"
_AUTH = "Atmosphere realm=http://atmosphere,atmosphere_app_id=WorkAndCoApp, atmosphere_signature_method=NONE"
_BASE = {"authorization": _AUTH, "access_type": "client_credentials", "channel": "web",
         "content-type": "application/json", "Origin": SITE, "Referer": SITE + "/", "Accept": "application/json"}
_lock = threading.Lock()
_session: cr.Session | None = None
_last = 0.0
_MIN_GAP = 0.5


@memo
def stations() -> set[str]:
    return set(json.loads((Path(__file__).parents[1] / "data" / "aeromexico_airports.json").read_text()))


def _pairs(origins: list[str], destinations: list[str]) -> list[tuple[str, str]]:
    st = stations()

    def cc(c):
        return a.country if (a := airports.get(c)) else None
    # Aeromexico and its partners' airports (the site's /tc/od/origin list).
    # Skip same country markets other than Mexico (those are partner flights).
    return [(o, d) for o in origins for d in destinations
            if o in st and d in st and o != d and (cc(o) != cc(d) or cc(o) == "MX")]


def relevant(origins: list[str], destinations: list[str]) -> bool:
    return bool(_pairs(origins, destinations))


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1) -> str:
    it = f"{origin}_{dest}_{dep}" + (f".{dest}_{origin}_{ret}" if ret else "")
    return f"{SITE}/en-us/book/options?itinerary={it}&leg=1&travelers=A{adults}_C0_I0_PH0_PC0"


def _get(url: str, headers: dict) -> dict:
    global _session, _last
    with _lock:
        if _session is None:
            _session = cr.Session(impersonate="chrome")
        wait = _MIN_GAP - (time.time() - _last)
        if wait > 0:
            time.sleep(wait)
        _last = time.time()
    r = _session.get(url, headers={**_BASE, **headers, "x-transactionid": str(uuid.uuid4())}, timeout=40)
    r.raise_for_status()
    return r.json()


def _citycode() -> str:
    key = "aeromexico:pcc:us"
    if (hit := cache.get(key, ttl=24 * 3600)) is None:
        hit = _get(f"{META}/tc/pcc/getPccInfo", {"storefront": "us", "project": "BOOKING"})["jipcc"]
        cache.put(key, hit)
    return hit


def _region(origin: str, dest: str) -> str:
    key = f"aeromexico:region:{origin}:{dest}"
    if (hit := cache.get(key, ttl=7 * 24 * 3600)) is None:
        hit = _get(f"{META}/tc/region/regionByRoute", {"departure": origin, "arrival": dest})["subRegionFinal"]
        cache.put(key, hit)
    return hit


def _families(cabin: str) -> tuple[str, ...]:
    return ("PREMIER",) if cabin in ("business", "first") else ("MAIN", "AMPLUS")


def parse(data: dict, adults: int = 1, cabin: str = "economy") -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
    """search/flight JSON -> (outbound, inbound), each {fare type: journeys}
    with the cheapest fare of that type per flight."""
    fams = _families(cabin)

    def side(opts) -> dict[str, list[dict]]:
        by: dict[str, list[dict]] = {}
        for o in opts or []:
            segs = [{"origin": s["departureAirport"], "destination": s["arrivalAirport"],
                     "departure": s["departureDateTime"], "arrival": s["arrivalDateTime"],
                     "carrier": s.get("marketingCarrier") or "AM", "number": s["marketingFlightCode"],
                     "aircraft": s.get("aircraftType"), "duration": s.get("duration")}
                    for leg in o.get("legCollection") or [] for s in leg.get("segments") or []]
            if not segs:
                continue
            dur = sum(leg.get("totalFlightDuration") or 0 for leg in o["legCollection"]) or None
            best: dict[str, tuple[float, dict]] = {}
            for f in o.get("fares") or []:
                if not str(f.get("fareFamily", "")).startswith(fams) or not (f.get("seatsRemaining") or 0) > 0:
                    continue
                total = ((f.get("currency") or {}).get("total"))
                if not total:
                    continue
                t = f.get("fareType") or "?"
                if t not in best or total < best[t][0]:
                    best[t] = (float(total), f)
            for t, (total, f) in best.items():
                by.setdefault(t, []).append({"segments": segs, "total": round(total * adults, 2),
                                             "fare": f.get("fareFamily"), "seats": f.get("seatsRemaining"),
                                             "duration": dur})
        return by

    return side(data.get("outbound")), side(data.get("inbound"))


def _search(origin: str, dest: str, dep: date, ret: date | None, adults: int) -> dict:
    key = f"aeromexico:{origin}:{dest}:{dep}:{ret}:{adults}"
    if (hit := cache.get(key)) is not None:
        return hit
    it = f"{origin}_{dest}_{dep}" + (f".{dest}_{origin}_{ret}" if ret else "")
    h = {"language": "EN", "isnewbf": "true", "store": "US", "locale": "UX", "currency": "USD",
         "iscorporateflow": "false", "cache-control": "no-cache", "travelers": f"A{adults}_C0_I0_PH0_PC0",
         "itinerary": it, "legregion": _region(origin, dest), "citycode": _citycode()}
    try:
        d = _get(f"{BOOK}/bc/{'rt' if ret else 'ow'}/search/flight", h)
    except Exception as e:  # 4xx for markets it does not sell
        if getattr(getattr(e, "response", None), "status_code", 500) in (400, 404):
            d = {}
        else:
            raise
    cache.put(key, d)
    return d


def search(q: SearchQuery) -> list[Itinerary]:
    pairs = _pairs(q.origins, q.destinations)
    if not pairs:
        return []
    out: list[Itinerary] = []
    for o, d in pairs[:3]:
        outs, backs = parse(_search(o, d, q.departure, q.return_date, q.adults), q.adults, q.cabin)
        url = deeplink(o, d, q.departure, q.return_date, q.adults)
        best: dict[str, Itinerary] = {}
        for t, js in outs.items():
            if q.return_date and not backs.get(t):
                continue
            for it in combine(q, "aeromexico", "Aeromexico", js, backs.get(t) if q.return_date else None, "USD",
                              url, {"AM": "Aeromexico"}, note="Aeromexico cheapest fare incl. taxes and TUA."):
                k = it.flight_key
                if k not in best or it.price < best[k].price:
                    best[k] = it
        out += best.values()
    return out
