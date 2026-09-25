"""Alaska Airlines (AS) and Hawaiian Airlines (HA, same booking site since the
merger) direct from alaskaair.com. The results page is SvelteKit: its own
data endpoint (/search/results/__data.json?<same query as the page>) streams
the fare grid as devalue encoded JSON, one line per chunk. Plain HTTP with
Chrome TLS impersonation (curl_cffi) gets it, no key. About 2 to 4 seconds.
(A headless Chrome sometimes gets Fastly's image captcha on the page itself;
the data endpoint has not been challenged.)

One request per direction: the page lists one way fares per passenger
("All fares are one-way per passenger, including taxes and fees"), so a round
trip is the sum of two one way searches. Price = the cheapest economy fare
family per flight (Saver, else Main) incl. taxes, what the page shows rounded
up to the dollar. Airports come from data/alaska_airports.json (the page's
own airport list, entries flagged ``isAlaska``)."""

from __future__ import annotations

import json
import threading
from datetime import date
from functools import cache as memo
from pathlib import Path

from curl_cffi import requests as cr

from .. import cache
from ..models import Itinerary, SearchQuery
from ._airline import combine

SITE = "https://www.alaskaair.com"
_lock = threading.Lock()
_session: cr.Session | None = None
NAMES = {"AS": "Alaska Airlines", "HA": "Hawaiian Airlines", "QX": "Horizon Air", "OO": "SkyWest"}
_FAMILIES = {
    "economy": ["SAVER", "MAIN", "REFUNDABLE_MAIN"],
    "premium": ["PREMIUM", "REFUNDABLE_PREMIUM"],
    "business": ["FIRST", "REFUNDABLE_FIRST"],
    "first": ["FIRST", "REFUNDABLE_FIRST"],
}


@memo
def airports() -> set[str]:
    return set(json.loads((Path(__file__).parents[1] / "data" / "alaska_airports.json").read_text()))


def _pairs(origins: list[str], destinations: list[str]) -> list[tuple[str, str]]:
    a = airports()
    return [(o, d) for o in origins for d in destinations if o != d and o in a and d in a]


def relevant(origins: list[str], destinations: list[str]) -> bool:
    return bool(_pairs(origins, destinations))


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1) -> str:
    q = f"A={adults}&C=0&L=0&O={origin}&D={dest}&OD={dep}&RT={'true' if ret else 'false'}"
    if ret:
        q += f"&DD={ret}"
    return f"{SITE}/search/results?{q}"


def unflatten(values: list):
    """Decode a devalue (SvelteKit) flattened payload; ``values[0]`` is the root."""
    memo_: dict[int, object] = {}

    def h(i):
        if isinstance(i, int) and i < 0:
            return None  # undefined, holes, NaN and friends
        if i in memo_:
            return memo_[i]
        v = values[i]
        if isinstance(v, list):
            if v and isinstance(v[0], str):  # typed value: ["Date", ...], ["Promise", id], ...
                t = v[0]
                if t == "Set":
                    out = [h(x) for x in v[1:]]
                elif t == "Map":
                    out = {str(h(v[k])): h(v[k + 1]) for k in range(1, len(v), 2)}
                elif t == "null":
                    out = {v[k]: h(v[k + 1]) for k in range(1, len(v), 2)}
                elif t == "Promise":
                    out = {"__promise": v[1]}
                else:
                    out = v[1] if len(v) > 1 else None
                memo_[i] = out
                return out
            lst: list = []
            memo_[i] = lst
            lst.extend(h(x) for x in v)
            return lst
        if isinstance(v, dict):
            d: dict = {}
            memo_[i] = d
            for k, x in v.items():
                d[k] = h(x)
            return d
        memo_[i] = v
        return v

    return h(0)


def results(text: str) -> dict:
    """The flight results object out of the streamed __data.json lines."""
    for line in text.splitlines():
        if not line.strip():
            continue
        node = json.loads(line)
        if node.get("type") == "chunk":
            x = unflatten(node["data"])
            if isinstance(x, dict) and "rows" in x:
                return x
    return {}


def parse(res: dict, adults: int = 1, cabin: str = "economy") -> list[dict]:
    """flight results -> journeys, cheapest fare family of the cabin."""
    fams = _FAMILIES.get(cabin, _FAMILIES["economy"])
    out = []
    for r in res.get("rows") or []:
        sols = r.get("solutions") or {}
        best = None
        for f in fams:
            s = sols.get(f)
            if s and s.get("grandTotal") and (s.get("seatsRemaining") or 1) > 0:
                if best is None or s["grandTotal"] < best[0]:
                    best = (float(s["grandTotal"]), f, s.get("seatsRemaining"))
        segs = r.get("segments") or []
        if not best or not segs:
            continue
        out.append({
            "segments": [{"origin": s["departureStation"], "destination": s["arrivalStation"],
                          "departure": s["departureTime"], "arrival": s["arrivalTime"],
                          "carrier": s["publishingCarrier"]["carrierCode"],
                          "number": s["publishingCarrier"]["flightNumber"], "duration": s.get("duration"),
                          "aircraft": s.get("aircraft")} for s in segs],
            "total": round(best[0] * adults, 2), "fare": best[1], "seats": best[2], "duration": r.get("duration"),
        })
    return out


def _fetch(o: str, d: str, day: date, adults: int) -> dict:
    global _session
    with _lock:
        if _session is None:
            _session = cr.Session(impersonate="chrome")
    url = (f"{SITE}/search/results/__data.json?A={adults}&C=0&L=0&O={o}&D={d}&OD={day}&RT=false"
           f"&x-sveltekit-invalidated=01")
    r = _session.get(url, timeout=45)  # no Referer: Fastly answers 406 to it
    r.raise_for_status()
    if "sveltekit" not in r.headers.get("content-type", "") and not r.text.startswith("{"):
        raise RuntimeError("alaska: challenged or site change (no SvelteKit data)")
    return results(r.text)


def _journeys(o: str, d: str, day: date, adults: int, cabin: str) -> list[dict]:
    key = f"alaska:{o}:{d}:{day}:{adults}"
    if (res := cache.get(key)) is None:
        res = _fetch(o, d, day, adults)
        res = {"rows": res.get("rows") or []}
        cache.put(key, res)
    return parse(res, 1, cabin)


def search(q: SearchQuery) -> list[Itinerary]:
    pairs = _pairs(q.origins, q.destinations)
    if not pairs:
        return []
    out: list[Itinerary] = []
    for o, d in pairs[:2]:
        # grandTotal is per passenger ("fares are one-way per passenger"), times adults
        outs = [dict(j, total=round(j["total"] * q.adults, 2)) for j in _journeys(o, d, q.departure, q.adults, q.cabin)]
        backs = None
        if q.return_date:
            backs = [dict(j, total=round(j["total"] * q.adults, 2))
                     for j in _journeys(d, o, q.return_date, q.adults, q.cabin)]
            if not backs:
                continue
        out += combine(q, "alaska", "Alaska Airlines", outs, backs, "USD",
                       deeplink(o, d, q.departure, q.return_date, q.adults), NAMES,
                       note="Alaska cheapest fare family (Saver if sold) incl. taxes, two one way fares.")
    return out
