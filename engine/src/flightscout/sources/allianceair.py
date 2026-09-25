"""Alliance Air (9I) direct from bookme.allianceair.in. India's state owned
regional airline (ATR turboprops on 50 odd airports, many UDAN routes to
small towns) that Kiwi and most OTAs don't sell.

Plain HTTP, what the booking site does itself: open the search page (a Yii
app; it hands out a CSRF token and embeds the route list ``_orgDesList``),
then POST its search form to ``/search-schedule``. The results page embeds
``this.dataSchedule = [...]`` with every flight and fare family; each item's
``fare_info.total_search_fare.amount`` is the total for all passengers incl.
airport fees and GST (the components are listed next to it). Verified
headless on the site: BLR-COK 5 Nov 2026, 2 adults, 9I507 INR 4,654 per
person, INR 9,308 selected, plus 9I508 back INR 9,534, "Total Cost" INR
18,842. Round trips come back from one POST, each direction priced on its
own. The site is slow (a few seconds per page)."""

from __future__ import annotations

import json
import re
import threading
from datetime import date, datetime

from curl_cffi import requests as cr

from .. import cache
from ..models import Itinerary, SearchQuery
from ._airline import combine

SITE = "https://bookme.allianceair.in"
NAMES = {"9I": "Alliance Air"}
_lock = threading.Lock()
_session: cr.Session | None = None


def _s() -> cr.Session:
    global _session
    with _lock:
        if _session is None:
            _session = cr.Session(impersonate="chrome")
        return _session


def _page(o: str = "", d: str = "") -> tuple[str, str]:
    """The search page (html, csrf token)."""
    r = _s().get(f"{SITE}/search-schedule", params={"org": o, "des": d} if o else None,
                 headers={"Referer": f"{SITE}/book"}, timeout=90)
    r.raise_for_status()
    csrf = re.search(r'name="csrf-token" content="([^"]+)"', r.text)
    return r.text, csrf.group(1) if csrf else ""


def routes_from(html: str) -> dict[str, list[str]]:
    m = re.search(r"var _orgDesList\s*=\s*(\[.*?\]);", html, re.S)
    net: dict[str, set[str]] = {}
    for x in json.loads(m.group(1)) if m else []:
        net.setdefault(x["origin"], set()).add(x["destination"])
    return {k: sorted(v) for k, v in net.items()}


def network() -> dict[str, list[str]]:
    key = "allianceair:network"
    if (hit := cache.get(key, ttl=3 * 86400)) is not None:
        return hit
    net = routes_from(_page()[0])
    if net:
        cache.put(key, net)
    return net


def relevant(origins: list[str], destinations: list[str]) -> bool:
    try:
        net = network()
    except Exception:
        return False
    return any(d in net.get(o, ()) for o in origins for d in destinations)


def deeplink(o: str, d: str) -> str:
    return f"{SITE}/search-schedule?org={o}&des={d}"


def _when(x: dict) -> str:
    return datetime(int(x["year"]), int(x["month"]), int(x["day"]), int(x["hour"]), int(x["minute"])).isoformat()


def schedule(html: str) -> dict:
    m = re.search(r"this\.dataSchedule\s*=\s*(\[[\s\S]*?\]);", html)
    if not m:
        raise RuntimeError("allianceair: no schedule on the results page")
    return next((x for x in json.loads(m.group(1)) if isinstance(x, dict)), {})


def parse(data: dict) -> tuple[list[dict], list[dict]]:
    """dataSchedule entry -> (outbound journeys, return journeys), each flight
    at its cheapest fare family, priced for all passengers."""
    res = []
    for k in ("departure_schedule", "return_schedule"):
        best: dict[tuple, dict] = {}
        for it in data.get(k) or []:
            fare = ((it.get("fare_info") or {}).get("total_search_fare") or {})
            amt = fare.get("amount") or fare.get("sum_amount")
            routes = it.get("connecting_flight_routes") or []
            if not amt or not routes:
                continue
            segs = []
            for r in routes:
                fn = str(r["flight_number"]).strip()
                segs.append({"origin": r["origin"]["code"], "destination": r["destination"]["code"],
                             "departure": _when(r["departure_date"]), "arrival": _when(r["arrival_date"]),
                             "carrier": fn[:2], "number": fn[2:], "aircraft": r.get("aircraft")})
            seats = min((int(r["availability"]) for r in routes if str(r.get("availability", "")).isdigit()),
                        default=None)
            j = {"segments": segs, "total": float(amt), "fare": (it.get("flight_metadata") or {}).get("fare_family"),
                 "seats": seats, "currency": fare.get("ccy") or "INR"}
            key = tuple((s["number"], s["departure"]) for s in segs)
            if key not in best or j["total"] < best[key]["total"]:
                best[key] = j
        res.append(list(best.values()))
    return res[0], res[1]


def _fetch(o: str, d: str, dep: date, ret: date | None, adults: int) -> dict:
    key = f"allianceair:{o}:{d}:{dep}:{ret}:{adults}"
    if (hit := cache.get(key)) is not None:
        return hit
    html, csrf = _page(o, d)
    form = {"org": o, "des": d, "dep_date": f"{dep:%d/%m/%Y}", "ret_date": f"{ret:%d/%m/%Y}" if ret else "",
            "pax": f"{adults} Adult", "adult": str(adults), "child": "0", "infant": "0", "ccy": "INR",
            "promo_code": "", "multi_route": "", "multi_date": "", "pax_category": "", "_csrf": csrf}
    r = _s().post(f"{SITE}/search-schedule", data=form, timeout=90, headers={
        "Referer": deeplink(o, d), "Origin": SITE, "X-CSRF-Token": csrf})
    r.raise_for_status()
    data = schedule(r.text)
    cache.put(key, data)
    return data


def search(q: SearchQuery) -> list[Itinerary]:
    if q.cabin != "economy" or not relevant(q.origins, q.destinations):
        return []
    net = network()
    out: list[Itinerary] = []
    pairs = [(o, d) for o in q.origins[:3] for d in q.destinations[:3] if d in net.get(o, ())]
    for o, d in pairs[:2]:
        outs, backs = parse(_fetch(o, d, q.departure, q.return_date, q.adults))
        if not outs or (q.return_date and not backs):
            continue
        out += combine(q, "allianceair", "Alliance Air", outs, backs if q.return_date else None,
                       outs[0]["currency"], deeplink(o, d), NAMES,
                       note="Alliance Air cheapest fare family (15 kg checked bag).")
    return out
