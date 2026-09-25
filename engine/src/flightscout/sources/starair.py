"""Star Air (S5) direct from its Hitit Crane booking engine
(book-sdg.crane.aero). Regional Indian airline (Embraer jets, UDAN routes
from Bengaluru, Mumbai, Hyderabad, Ahmedabad, ...) that Kiwi and most OTAs
don't sell.

Plain HTTP, see _c_crane.py; the host needs a session cookie from its search
form first. Prices are per passenger incl. taxes in INR: 2 adults BLR-GBI
6 Nov 2026 showed STAR REGULAR INR 4,500 and a cart TOTAL PRICE of INR
9,000 (verified headless). Economy ("STAR REGULAR"/"STAR FLEXI") and
Business brands. Nonstop flights only."""

from __future__ import annotations

import re
from datetime import date

from .. import cache
from ..models import Itinerary, SearchQuery
from ._airline import combine, countries
from ._c_crane import Crane, parse

NAMES = {"S5": "Star Air"}
CRANE = Crane("starair", "https://book-sdg.crane.aero", warm=True)


def ports() -> set[str]:
    key = "starair:ports"
    if (hit := cache.get(key, ttl=7 * 86400)) is not None:
        return set(hit)
    r = CRANE._s().get(f"{CRANE.host}/ibe/search/portNames", timeout=30,
                       headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"})
    r.raise_for_status()
    codes = sorted(set(re.findall(r'([A-Z]{3})\\?"\s*:', r.text)))
    if codes:
        cache.put(key, codes)
    return set(codes)


def _ok(o: str, d: str, net: set[str]) -> bool:
    return o != d and o in net and d in net and "IN" in (countries([o]) | countries([d]))


def relevant(origins: list[str], destinations: list[str]) -> bool:
    try:
        net = ports()
    except Exception:
        return False
    return any(_ok(o, d, net) for o in origins for d in destinations)


def deeplink(o: str, d: str, dep: date, ret: date | None = None, adults: int = 1) -> str:
    return CRANE.url(o, d, dep, ret, adults)


def search(q: SearchQuery) -> list[Itinerary]:
    if q.cabin not in ("economy", "business") or not relevant(q.origins, q.destinations):
        return []
    net = ports()
    out: list[Itinerary] = []
    pairs = [(o, d) for o in q.origins[:3] for d in q.destinations[:3] if _ok(o, d, net)]
    for o, d in pairs[:3]:
        res = parse(CRANE.fetch(o, d, q.departure, q.return_date, q.adults), q.adults, q.cabin, o, d)
        outs = [j for j in res["OUTBOUND"] if j["segments"][0]["origin"] == o]
        backs = [j for j in res["INBOUND"] if j["segments"][0]["origin"] == d] if q.return_date else None
        if not outs or (q.return_date and not backs):
            continue
        out += combine(q, "starair", "Star Air", outs, backs, outs[0].get("currency") or "INR",
                       deeplink(o, d, q.departure, q.return_date, q.adults), NAMES,
                       note="Star Air cheapest fare in the cabin. Nonstop flights only.")
    return out
