"""Arajet (DM) direct from arajet.com's own shopping API (POST /pss/shop/airshop),
the call its booking page makes. Arajet is a Dominican ULCC with connections
through Santo Domingo all over the Americas; OTAs and Google often miss its
cheapest fares.

No key and no session: plain JSON with Chrome TLS impersonation (curl_cffi)
passes Cloudflare. One call prices a whole round trip (the site does the
same, and round trip fares differ a little from two one ways, the Dominican
departure tax). ``totalAmount`` is per passenger incl. taxes, fuel surcharge
and fees, the "From" price the page shows for the Basic fare. Some Arajet
connections include a bus leg (equipment BUS, e.g. Punta Cana to Santo
Domingo), kept as a segment with a warning.

Routes come from data/arajet_routes.json (the site's own /pss/routes, which
already lists connecting markets); refresh it when Arajet changes its
network."""

from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import date, datetime
from functools import cache as memo
from pathlib import Path

from curl_cffi import requests as cr

from .. import cache
from ..models import Itinerary, SearchQuery
from ._airline import combine

SITE = "https://www.arajet.com"
_lock = threading.Lock()
_session: cr.Session | None = None
_last = 0.0
_MIN_GAP = 0.6


@memo
def routes() -> dict[str, set[str]]:
    raw = json.loads((Path(__file__).parents[1] / "data" / "arajet_routes.json").read_text())
    return {o: set(ds) for o, ds in raw.items()}


def _pairs(origins: list[str], destinations: list[str]) -> list[tuple[str, str]]:
    r = routes()
    return [(o, d) for o in origins for d in destinations if d in r.get(o, ())]


def relevant(origins: list[str], destinations: list[str]) -> bool:
    return bool(_pairs(origins, destinations))


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1) -> str:
    return (f"{SITE}/en-us/booking?origin={origin}&destination={dest}&from={dep}"
            + (f"&to={ret}" if ret else "") + f"&adt={adults}&chd=0&inf=0&currency=USD")


def _post(body: dict) -> dict:
    global _session, _last
    with _lock:
        if _session is None:
            _session = cr.Session(impersonate="chrome")
        wait = _MIN_GAP - (time.time() - _last)
        if wait > 0:
            time.sleep(wait)
        _last = time.time()
    h = {"X-Point-Of-Sale": "US", "X-Currency": "USD", "Language": "en", "Content-Type": "application/json",
         "X-Correlation-Id": str(uuid.uuid4()), "Origin": SITE, "Referer": f"{SITE}/en-us/booking",
         "Accept": "application/json"}
    r = _session.post(f"{SITE}/pss/shop/airshop", json=body, headers=h, timeout=30)
    r.raise_for_status()
    return r.json()


def _hm(t: str) -> str:
    """'3:05 PM' -> '15:05'."""
    hm, ap = t.split()
    h, m = (int(x) for x in hm.split(":"))
    h = h % 12 + (12 if ap.upper() == "PM" else 0)
    return f"{h:02d}:{m:02d}"


def _iso(p: dict) -> str:
    return f"{p['date']}T{_hm(p['time'])}"


def parse(data: dict, origin: str, adults: int = 1) -> tuple[list[dict], list[dict]]:
    """airshop JSON -> (outbound, return) journeys; return is empty for one ways."""
    outs, backs = [], []
    for it in ((data.get("content") or {}).get("flightSegmentItineraries") or {}).get("items") or []:
        fl = (it.get("flights") or {}).get("items") or []
        if not fl or any((f.get("status") or {}).get("code") not in (None, "A") for f in fl):
            continue
        best = None
        for fp in (it.get("fareProducts") or {}).get("items") or []:
            for p in (fp.get("prices") or {}).get("items") or []:
                if p.get("key") == "ADT" and (p.get("totalAmount") or {}).get("value"):
                    v = float(p["totalAmount"]["value"])
                    if best is None or v < best[0]:
                        best = (v, fp.get("typeCode"))
        if not best:
            continue
        segs = [{"origin": f["locationDepart"]["code"], "destination": f["locationArrive"]["code"],
                 "departure": _iso(f["scheduledDepart"]), "arrival": _iso(f["scheduledArrive"]),
                 "carrier": (f.get("airlineOperating") or {}).get("code") or "DM", "number": f["flightNumber"],
                 "aircraft": "BUS" if (f.get("equipment") or {}).get("code") == "BUS"
                 else (f.get("equipment") or {}).get("description")} for f in fl]
        # exact duration from the GMT times
        g0, g1 = fl[0]["scheduledDepart"], fl[-1]["scheduledArrive"]
        dur = (datetime.fromisoformat(f"{g1['gMTDate']}T{_hm(g1['gMTTime'])}")
               - datetime.fromisoformat(f"{g0['gMTDate']}T{_hm(g0['gMTTime'])}"))
        seats = min((f.get("classOfService") or {}).get("count") or 99 for f in fl)
        j = {"segments": segs, "total": round(best[0] * adults, 2), "fare": best[1],
             "duration": int(dur.total_seconds() // 60), "seats": seats if seats < 99 else None}
        (outs if segs[0]["origin"] == origin else backs).append(j)
    return outs, backs


def search(q: SearchQuery) -> list[Itinerary]:
    pairs = _pairs(q.origins, q.destinations)
    if not pairs or q.cabin != "economy":
        return []
    out: list[Itinerary] = []
    for o, d in pairs[:4]:
        key = f"arajet:{o}:{d}:{q.departure}:{q.return_date}"
        if (data := cache.get(key)) is None:
            shops = [{"dateTimeDepart": {"date": str(q.departure)}, "locationDepart": {"code": o},
                      "locationArrive": {"code": d}}]
            if q.return_date:
                shops.append({"dateTimeDepart": {"date": str(q.return_date)}, "locationDepart": {"code": d},
                              "locationArrive": {"code": o}})
            data = _post({"passengerTypes": {"items": [{"code": "ADT", "count": q.adults}]},
                          "itineraryShops": {"items": shops},
                          "attributeItems": {"items": [{"typeCode": "language", "code": "EN"}]}})
            cache.put(key, data)
        outs, backs = parse(data, o, q.adults)
        if q.return_date and not backs:
            continue
        url = deeplink(o, d, q.departure, q.return_date, q.adults)
        its = combine(q, "arajet", "Arajet", outs, backs if q.return_date else None, "USD", url,
                      {"DM": "Arajet"}, note="Arajet Basic fare incl. taxes; bags and seats extra.")
        for it in its:
            if any(s.aircraft == "BUS" for sl in it.slices for s in sl.segments):
                it.warnings.append("Includes an Arajet bus transfer leg.")
        out += its
    return out
