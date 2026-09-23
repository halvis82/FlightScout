"""Widerøe (WF) direct from wideroe.no. Google Flights has most Widerøe
schedules but usually no price (the regional PSO network especially), and
Kiwi only has part of it, so this source fills a real gap.

No key and no JSON API to call: the booking page
(/en/book-flight/flight?...) is a Next.js server render and the full
availability response (Amadeus DX "airBounds" with every fare family and its
total price incl. taxes) is embedded in the React Server Components payload
(``self.__next_f.push`` chunks). We fetch that page with Chrome TLS
impersonation (Cloudflare fronts the site) and parse the bounds out of it.

Prices are the total for all passengers in NOK incl. taxes and fees. The page
shows one bound at a time, so round trips are priced as two one ways (that is
how Widerøe sells them: the return price is independent of the outbound)."""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import date, datetime

from curl_cffi import requests as cr

from .. import cache
from ..models import Itinerary, SearchQuery, Segment, Slice

SITE = "https://www.wideroe.no"
AIRPORTS_URL = "https://webapi.wideroe.no/booking/airlineSpecificAirports?language=en&airline=WF"
_lock = threading.Lock()
_session: cr.Session | None = None
_last = 0.0
_MIN_GAP = 1.0  # seconds between page fetches, to stay polite

# Fallback network if the airport list endpoint is down. Widerøe is mostly
# Norwegian domestic with a few routes to nearby countries.
_FALLBACK = {
    "ABZ", "AES", "ALF", "ANX", "BGO", "BJF", "BLL", "BNN", "BOO", "BRU", "BVG", "CPH", "DUB", "EVE",
    "FAE", "FDE", "FLR", "FRO", "GOT", "HAA", "HAM", "HAU", "HFT", "HOV", "HVG", "KKN", "KRS", "KSU",
    "LKL", "LKN", "MEH", "MJF", "MOL", "MQN", "MUC", "NCE", "OSL", "OSY", "RET", "RVK", "SDN", "SKN",
    "SOG", "SOJ", "SSJ", "SVG", "SVJ", "TOS", "TRD", "TRF", "VAW", "VDS",
}
_ABROAD = {"ABZ", "BRU", "CPH", "DUB", "GOT", "HAM", "MUC", "NCE", "FLR", "AAL", "AAR"}
_FARE_NAMES = {"HAPPYLIG": "Mini", "HAPPY": "Smart", "ECOFLEX": "Flex", "FULLFLEX": "Full Flex"}
_BOUND = re.compile(r'\{"boundType":"(\w+)","bound":\{')
_CHUNK = re.compile(r'self\.__next_f\.push\(\[1,(".*?")\]\)</script>', re.S)


def _sess() -> cr.Session:
    global _session
    if _session is None:
        _session = cr.Session(impersonate="chrome")
    return _session


def network() -> dict[str, str]:
    """Widerøe airports -> country name, from the site's own airport list."""
    key = "wideroe:airports"
    if (hit := cache.get(key, ttl=7 * 86400)) is not None:
        return hit
    try:
        r = _sess().get(AIRPORTS_URL, timeout=20)
        r.raise_for_status()
        net = {a["airportCode"]: a["country"] for a in r.json()["airports"] if len(a["airportCode"]) == 3}
        if net:
            cache.put(key, net)
            return net
    except Exception:
        pass
    return {c: "Norway" if c not in _ABROAD else "abroad" for c in _FALLBACK}


def relevant(origins: list[str], destinations: list[str]) -> bool:
    """Both sides must include a Widerøe airport and at least one of them must
    be in Norway (every Widerøe route touches Norway)."""
    net = network()
    o = [c for c in origins if c in net]
    d = [c for c in destinations if c in net]
    return bool(o and d) and any(net[c] == "Norway" for c in o + d)


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1) -> str:
    q = (f"d_city={origin.lower()}&a_city={dest.lower()}&pax={'_'.join(['adt'] * adults)}"
         f"&triptype={2 if ret else 1}&d_day={dep:%d}&d_month={dep:%Y%m}")
    if ret:
        q += f"&r_day={ret:%d}&r_month={ret:%Y%m}"
    return f"{SITE}/en/book-flight/flight?{q}"


def _fetch(url: str) -> str:
    global _last
    with _lock:
        wait = _MIN_GAP - (time.time() - _last)
        if wait > 0:
            time.sleep(wait)
        _last = time.time()
    r = _sess().get(url, timeout=90)
    r.raise_for_status()
    return r.text


def _parse(html: str) -> list[dict]:
    rsc = "".join(json.loads(c) for c in _CHUNK.findall(html))
    dec = json.JSONDecoder()
    seen: set[tuple] = set()
    out = []
    for m in _BOUND.finditer(rsc):
        if m.group(1) != "outbound":
            continue
        try:
            obj, _ = dec.raw_decode(rsc, m.start())
        except ValueError:
            continue
        b = obj["bound"]
        fid = tuple(s["flightId"] for s in b["segments"])
        if fid in seen:
            continue  # the page renders each bound twice (mobile and desktop)
        seen.add(fid)
        best = None
        for off in b.get("airBoundOffers") or []:
            if off.get("status") != "AVAILABLE":
                continue
            tp = (off.get("prices") or {}).get("totalPrices") or []
            if not tp:
                continue
            p = tp[0]["total"] / 10 ** (tp[0].get("decimalPlaces") or 0)
            if best is None or p < best[0]:
                best = (p, tp[0]["currencyCode"], off.get("fareFamilyCode"), off.get("availableQuota"))
        if not best:
            continue
        segs = [{
            "origin": s["departure"]["airportCode"], "destination": s["arrival"]["airportCode"],
            "departure": s["departure"]["scheduledDateTime"], "arrival": s["arrival"]["scheduledDateTime"],
            "carrier": s.get("operatingAirlineCode") or s["marketingAirlineCode"],
            "number": s["marketingFlightNumber"], "duration": s.get("duration"),
            "aircraft": s.get("aircraftName"),
        } for s in b["segments"]]
        out.append({"segments": segs, "total": best[0], "currency": best[1], "fare": best[2],
                    "seats": best[3], "duration": b.get("duration")})
    return out


def _flights(origin: str, dest: str, day: date, adults: int) -> list[dict]:
    key = f"wideroe:{origin}:{dest}:{day}:{adults}"
    if (hit := cache.get(key)) is not None:
        return hit
    out = _parse(_fetch(deeplink(origin, dest, day, adults=adults)))
    cache.put(key, out)
    return out


def _slice(j: dict) -> Slice:
    segs = [Segment(
        origin=s["origin"], destination=s["destination"],
        # local wall clock times, like every other source
        departure=datetime.fromisoformat(s["departure"]).replace(tzinfo=None),
        arrival=datetime.fromisoformat(s["arrival"]).replace(tzinfo=None),
        carrier=s["carrier"], carrier_name="Widerøe" if s["carrier"] == "WF" else None,
        flight_number=s["number"], duration_min=(s["duration"] // 60) if s.get("duration") else None,
        aircraft=s.get("aircraft"),
    ) for s in j["segments"]]
    if j.get("duration"):
        dur = j["duration"] // 60
    else:  # offsets are in the timestamps, so this is exact
        dur = int((datetime.fromisoformat(j["segments"][-1]["arrival"])
                   - datetime.fromisoformat(j["segments"][0]["departure"])).total_seconds() // 60)
    return Slice(segments=segs, duration_min=max(dur, 1))


def search(q: SearchQuery) -> list[Itinerary]:
    if not relevant(q.origins, q.destinations):
        return []
    net = network()
    out: list[Itinerary] = []
    for o in [c for c in q.origins if c in net][:3]:
        for d in [c for c in q.destinations if c in net][:3]:
            if o == d:
                continue
            outs = _flights(o, d, q.departure, q.adults)
            backs = _flights(d, o, q.return_date, q.adults) if q.return_date else [None]
            if q.max_stops is not None:
                outs = [x for x in outs if len(x["segments"]) - 1 <= q.max_stops]
                if q.return_date:
                    backs = [x for x in backs if len(x["segments"]) - 1 <= q.max_stops]
            outs = sorted(outs, key=lambda x: x["total"])[:6]
            backs = sorted(backs, key=lambda x: x["total"])[:6] if q.return_date else [None]
            for a in outs:
                for b in backs:
                    slices = [_slice(a)] + ([_slice(b)] if b else [])
                    total = a["total"] + (b["total"] if b else 0)
                    warn = []
                    if (a["seats"] and a["seats"] <= 3) or (b and b["seats"] and b["seats"] <= 3):
                        warn.append("Only a few seats left at this Widerøe fare.")
                    fares = " + ".join(_FARE_NAMES.get(x["fare"], x["fare"] or "?") for x in (a, b) if x)
                    warn.append(f"Widerøe {fares} fare (cheapest bookable family).")
                    out.append(Itinerary(
                        source="wideroe", price=round(total, 2), currency=a["currency"], slices=slices,
                        booking_url=deeplink(o, d, q.departure, q.return_date, q.adults),
                        seller="Widerøe", seller_kind="airline", warnings=warn,
                    ))
    return out
