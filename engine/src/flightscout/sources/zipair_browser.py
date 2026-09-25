"""ZIPAIR (ZG) direct from zipair.net through the shared real Chrome (see
_browser.py). ZIPAIR sells only on its own site (no GDS), so Google and Kiwi
often lack its fares, including its self sold connections via Narita.

Its booking API (bff.zipair.net) sits behind Cloudflare, which answers plain
HTTP clients with 403, so we open www.zipair.net in Chrome and call the same
JSON endpoints the site uses from inside the page (``fetch`` with the page's
cookies): /v2/flights/routes (every sellable route, nonstop or via NRT) and
/v2/flights (every flight in a date range with each cabin's fare and taxes).
One page load plus one call per direction, about 6 to 10 seconds, headless.

Prices: per adult fare ``originalAmount`` plus that segment's taxes, summed
over segments, plus the connection fee on transit tickets, in JPY. Times come
in UTC and are converted to local time with each airport's zone (the API's
date range is in UTC, so we ask for the day before and after and keep the
flights leaving on the requested local date). Round trips are two one ways,
which is how ZIPAIR prices them."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .. import cache
from ..models import Itinerary, SearchQuery
from . import _browser
from ._airline import combine

log = logging.getLogger(__name__)
SITE = "https://www.zipair.net"
BFF = "https://bff.zipair.net"
NAMES = {"ZG": "ZIPAIR"}
CURRENCY = "JPY"
# ZIPAIR stations and their time zones (the API gives UTC times).
TZ = {
    "NRT": "Asia/Tokyo", "HND": "Asia/Tokyo", "KIX": "Asia/Tokyo", "ICN": "Asia/Seoul", "TPE": "Asia/Taipei",
    "BKK": "Asia/Bangkok", "SIN": "Asia/Singapore", "KUL": "Asia/Kuala_Lumpur", "MNL": "Asia/Manila",
    "CEB": "Asia/Manila", "HNL": "Pacific/Honolulu", "YVR": "America/Vancouver", "SFO": "America/Los_Angeles",
    "SJC": "America/Los_Angeles", "LAX": "America/Los_Angeles", "SEA": "America/Los_Angeles",
    "IAH": "America/Chicago", "MCO": "America/New_York",
}
_CABIN = {"economy": "STANDARD", "premium": "STANDARD", "business": "ZIPFULLFLAT", "first": "ZIPFULLFLAT"}
_FETCH = """async u => { const r = await fetch(u, {credentials: 'include', headers: {accept: 'application/json'}});
                        return [r.status, await r.text()]; }"""


def available() -> bool:
    return _browser.available()


def relevant(origins: list[str], destinations: list[str]) -> bool:
    if not available():
        return False
    return any(o in TZ for o in origins) and any(d in TZ for d in destinations)


def deeplink() -> str:
    """ZIPAIR's search keeps its state server side, so there is no search
    deeplink: this opens the home page search form."""
    return f"{SITE}/en"


def _local(ts: str, airport: str) -> str:
    t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return t.astimezone(ZoneInfo(TZ[airport])).isoformat()


def parse(data: dict, day: date, adults: int = 1, cabin: str = "economy") -> list[dict]:
    """/v2/flights JSON -> journeys leaving on local ``day``, priced for the
    cabin (STANDARD or ZIPFULLFLAT) incl. taxes and connection fee."""
    want = _CABIN.get(cabin, "STANDARD")
    conn = float(((data.get("connectionFee") or {}).get("amount")) or 0)
    out = []
    for it in data.get("flights") or []:
        if not it or any(s["origin"] not in TZ or s["destination"] not in TZ for s in it):
            continue
        segs, total, seats = [], 0.0, None
        for s in it:
            fare = next((f for f in s.get("fares") or [] if f.get("passengerType") == "adult"
                         and f.get("cabinCode") == want), None)
            if not fare:
                break
            total += float(fare["amounts"]["originalAmount"]) + sum(float(t["amount"]) for t in fare.get("taxes") or [])
            seats = min(seats or 999, fare.get("availableSeat") or 999)
            t = s["scheduledDepartureArrivalDateTime"]
            segs.append({"origin": s["origin"], "destination": s["destination"],
                         "departure": _local(t["departureDate"], s["origin"]),
                         "arrival": _local(t["arrivalDate"], s["destination"]),
                         "carrier": s.get("carrierCode") or "ZG", "number": str(s["flightNumber"]).lstrip("0"),
                         "duration": s.get("flightTime")})
        else:
            if datetime.fromisoformat(segs[0]["departure"]).date() != day:
                continue
            if len(segs) > 1:
                total += conn
            out.append({"segments": segs, "total": round(total * adults, 2),
                        "seats": seats if seats and seats < 999 else None, "fare": want})
    return out


def _routes_param(routes: list, o: str, d: str) -> list[str]:
    """Sellable route variants from o to d as the API's ``routes`` values
    (NRT,ICN or ICN,NRT,BKK)."""
    out = []
    for r in routes:
        if r and r[0]["origin"] == o and r[-1]["destination"] == d:
            out.append(",".join([r[0]["origin"]] + [x["destination"] for x in r]))
    return out


def _fetch(pairs: list[tuple[str, str, date]], adults: int) -> tuple[list, dict]:
    """In one browser job: the route list (cached a day) and /v2/flights for
    each (origin, dest, day). Returns (routes, {key: flights JSON})."""
    routes = cache.get("zipair:routes", ttl=86400)

    def job(page) -> tuple[list, dict]:
        nonlocal routes
        if not page.url.startswith(SITE):
            page.goto(f"{SITE}/en", wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(1500)
        if routes is None:
            st, body = page.evaluate(_FETCH, f"{BFF}/v2/flights/routes?language=en")
            if st != 200:
                raise RuntimeError(f"zipair: routes HTTP {st}")
            routes = json.loads(body)["routes"]
        res = {}
        for o, d, day in pairs:
            for rp in _routes_param(routes, o, d):
                url = (f"{BFF}/v2/flights?adult={adults}&childA=0&childB=0&childC=0&infant=0"
                       f"&routes={rp.replace(',', '%2C')}&currency={CURRENCY}&language=en"
                       f"&departureDateFrom={day - timedelta(days=1)}&departureDateTo={day + timedelta(days=1)}")
                st, body = page.evaluate(_FETCH, url)
                if st != 200:
                    raise RuntimeError(f"zipair: flights HTTP {st} {body[:120]!r}")
                res[f"{rp}:{day}"] = json.loads(body)
        return routes, res

    routes_, res = _browser.run(job, "zipair", timeout=120)
    cache.put("zipair:routes", routes_)
    return routes_, res


def _bound(o: str, d: str, day: date, adults: int, cabin: str) -> list[dict]:
    key = f"zipair:{o}:{d}:{day}:{adults}"
    if (hit := cache.get(key)) is None:
        routes, res = _fetch([(o, d, day)], adults)
        hit = [v for k, v in res.items()]
        cache.put(key, hit)
    return [j for data in hit for j in parse(data, day, adults, cabin)]


def search(q: SearchQuery) -> list[Itinerary]:
    if not relevant(q.origins, q.destinations):
        return []
    out: list[Itinerary] = []
    for o in [c for c in q.origins if c in TZ][:2]:
        for d in [c for c in q.destinations if c in TZ][:2]:
            if o == d:
                continue
            outs = _bound(o, d, q.departure, q.adults, q.cabin)
            backs = _bound(d, o, q.return_date, q.adults, q.cabin) if q.return_date and outs else None
            if not outs or (q.return_date and not backs):
                continue
            fam = "ZIP Full-Flat" if _CABIN.get(q.cabin) == "ZIPFULLFLAT" else "Standard"
            out += combine(q, "zipair", "ZIPAIR", outs, backs, CURRENCY, deeplink(), NAMES,
                           note=f"ZIPAIR {fam} seat fare incl. taxes; bags, seats and meals are extra.")
    return out
