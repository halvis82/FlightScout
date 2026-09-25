"""Avelo Airlines (XP) direct from aveloair.com through the shared headless
Chrome (see _browser.py). Avelo sells only on its own site and Google often
lacks its fares. The booking app is a Blazor WebAssembly app whose shop API
keeps the search in a server side session guarded by an XSRF token, so we
let the real page run: open the deeplink the site's own booking widget
builds (/flight-search/deeplink/searchflights/oneway/HVN/MCO/2026-11-10/1/0/0/0/)
and capture the ``ShopService/search/airshop/<id>`` JSON the select page
fetches. One call covers both directions of a round trip. About 10 to 15
seconds per search (the WebAssembly app is heavy).

Price = the "Standard" fare product (base fare plus taxes and carrier
charges), what the page shows as Standard, rounded there to the dollar. The
cheaper "Subscription" price needs a paid Avelo PLUS membership and is
ignored. Routes come from data/avelo_routes.json (the site's own
/flight-search/services/routes/all); refresh it when Avelo changes its
network."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from functools import cache as memo
from pathlib import Path

from .. import cache
from ..models import Itinerary, SearchQuery
from . import _browser
from ._airline import combine

log = logging.getLogger(__name__)
SITE = "https://www.aveloair.com"


@memo
def routes() -> dict[str, set[str]]:
    raw = json.loads((Path(__file__).parents[1] / "data" / "avelo_routes.json").read_text())
    return {o: set(ds) for o, ds in raw.items()}


def available() -> bool:
    return _browser.available()


def _pairs(origins: list[str], destinations: list[str]) -> list[tuple[str, str]]:
    r = routes()
    return [(o, d) for o in origins for d in destinations if o != d and d in r.get(o, ())]


def relevant(origins: list[str], destinations: list[str]) -> bool:
    return bool(_pairs(origins, destinations)) and available()


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1) -> str:
    dates = f"{dep}/{ret}" if ret else f"{dep}"
    return (f"{SITE}/flight-search/deeplink/searchflights/{'roundtrip' if ret else 'oneway'}/{origin}/{dest}/"
            f"{dates}/{adults}/0/0/0/?calendar=false")


def _time(d: str, t: str) -> datetime:
    return datetime.strptime(f"{d} {t}", "%Y-%m-%d %I:%M %p")


def parse(data: dict, adults: int = 1) -> dict[str, list[dict]]:
    """airshop JSON -> journeys keyed by "ORIGIN-DEST" of the whole journey."""
    out: dict[str, list[dict]] = {}
    for it in ((data.get("FlightSegmentItineraries") or {}).get("Items")) or []:
        best = None
        for fp in ((it.get("FareProducts") or {}).get("Items")) or []:
            if fp.get("Description") != "Standard":
                continue
            for p in ((fp.get("Prices") or {}).get("Items")) or []:
                v = float(p["BaseAmount"]["Value"]) + sum(float(c["Value"]) for c in (p.get("Charges") or {}).get("Items") or [])
                if best is None or v < best:
                    best = v
        flights = ((it.get("Flights") or {}).get("Items")) or []
        if best is None or not flights:
            continue
        segs, seats = [], None
        for f in flights:
            dep = _time(f["ScheduledDepart"]["Date"], f["ScheduledDepart"]["Time"])
            arr = _time(f["ScheduledArrive"]["Date"], f["ScheduledArrive"]["Time"])
            segs.append({"origin": f["LocationDepart"]["Code"], "destination": f["LocationArrive"]["Code"],
                         "departure": dep.isoformat(), "arrival": arr.isoformat(),
                         "carrier": (f.get("AirlineMarketing") or {}).get("Code") or "XP", "number": f["FlightNumber"],
                         "aircraft": (f.get("Equipment") or {}).get("Description", "").strip() or None})
            n = (f.get("ClassOfService") or {}).get("Count")
            if n is not None:
                seats = n if seats is None else min(seats, n)
        gd = _time(flights[0]["ScheduledDepart"]["GMTDate"], flights[0]["ScheduledDepart"]["GMTTime"])
        ga = _time(flights[-1]["ScheduledArrive"]["GMTDate"], flights[-1]["ScheduledArrive"]["GMTTime"])
        key = f"{segs[0]['origin']}-{segs[-1]['destination']}"
        out.setdefault(key, []).append({"segments": segs, "total": round(best * adults, 2), "seats": seats,
                                        "duration": int((ga - gd).total_seconds() // 60)})
    return out


def _fetch(url: str) -> dict:
    def job(page) -> str:
        got = _browser.capture(page, lambda: page.goto(url, wait_until="commit", timeout=45000),
                               lambda u: "/ShopService/search/airshop/" in u and "calendar" not in u,
                               timeout=60, body=lambda t: "FlightSegmentItineraries" in t)
        return got[-1][1] if got else ""

    txt = _browser.run(job, "avelo", timeout=120)
    if not txt:
        raise RuntimeError("avelo: no airshop response (site change or no flights)")
    return json.loads(txt)


def search(q: SearchQuery) -> list[Itinerary]:
    pairs = _pairs(q.origins, q.destinations)
    if not pairs or not available() or q.cabin != "economy":
        return []
    out: list[Itinerary] = []
    for o, d in pairs[:2]:
        url = deeplink(o, d, q.departure, q.return_date, q.adults)
        key = f"avelo:{o}:{d}:{q.departure}:{q.return_date}:{q.adults}"
        if (data := cache.get(key)) is None:
            data = _fetch(url)
            cache.put(key, data)
        js = parse(data, q.adults)
        outs = [j for j in js.get(f"{o}-{d}", []) if j["segments"][0]["departure"][:10] == str(q.departure)]
        backs = [j for j in js.get(f"{d}-{o}", []) if j["segments"][0]["departure"][:10] == str(q.return_date)]
        if q.return_date and not backs:
            continue
        out += combine(q, "avelo", "Avelo Airlines", outs, backs if q.return_date else None, "USD", url,
                       {"XP": "Avelo Airlines"}, note="Avelo Standard fare incl. taxes; bags and seats extra.")
    return out
