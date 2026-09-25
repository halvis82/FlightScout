"""Allegiant (G4) direct from allegiantair.com through the shared real Chrome
(see _browser.py). Allegiant sells only on its own site (no OTAs, and Google
rarely prices it), and Cloudflare challenges plain HTTP clients and headless
Chrome, so this runs in the shared headful browser (window off screen and
minimized) and is skipped where there is no display.

Flow: load the home page once per session to pass the Cloudflare check, then
open the results deeplink the search form itself builds
(/booking/flights?tt=ONEWAY&o=LAS&d=BLI&ds=2026-11-06&...) and capture the
``flights`` GraphQL response the page makes. One call covers both directions
of a round trip. ``price`` is per person in USD incl. taxes and carrier
charges (what the page shows); bags and seats are extra. About 2 seconds per
search once warm (about 12 for the first).

Routes come from data/allegiant_routes.json (the site's own route map, the
``flightLocations`` of its initialData query); refresh it when Allegiant
changes its network."""

from __future__ import annotations

import json
import logging
from datetime import date
from functools import cache as memo
from pathlib import Path

from .. import cache
from ..models import Itinerary, SearchQuery
from . import _browser
from ._airline import combine

log = logging.getLogger(__name__)
SITE = "https://www.allegiantair.com"


@memo
def routes() -> dict[str, set[str]]:
    raw = json.loads((Path(__file__).parents[1] / "data" / "allegiant_routes.json").read_text())
    return {o: set(ds) for o, ds in raw.items()}


def available() -> bool:
    return _browser.available(headful=True)


def _pairs(origins: list[str], destinations: list[str]) -> list[tuple[str, str]]:
    r = routes()
    return [(o, d) for o in origins for d in destinations if d in r.get(o, ())]


def relevant(origins: list[str], destinations: list[str]) -> bool:
    return bool(_pairs(origins, destinations)) and available()


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1) -> str:
    return (f"{SITE}/booking/flights?tt={'ROUNDTRIP' if ret else 'ONEWAY'}&o={origin}&d={dest}&ta={adults}"
            f"&tc=0&tis=0&til=0&ds={dep}&de={ret or ''}&c=0&h=0")


def parse(data: dict, adults: int = 1) -> tuple[list[dict], list[dict]]:
    """``flights`` GraphQL response -> (departing, returning) journeys."""
    f = ((data.get("data") or {}).get("flights")) or {}

    def leg(opts) -> list[dict]:
        out = []
        for o in opts or []:
            fl = o.get("flight") or {}
            if o.get("price") is None or not fl:
                continue
            out.append({
                "segments": [{"origin": fl["origin"]["code"], "destination": fl["destination"]["code"],
                              "departure": fl["departingTime"], "arrival": fl["arrivalTime"],
                              "carrier": (fl.get("operatedBy") or "G4") if len(fl.get("operatedBy") or "") == 2 else "G4",
                              "number": fl["number"]}],
                "total": round(float(o["price"]) * adults, 2), "seats": o.get("availableSeatsCount"),
            })
        return out

    return leg(f.get("departing")), leg(f.get("returning"))


def _fetch(url: str) -> dict:
    def job(page) -> str:
        if "allegiantair.com" not in page.url:  # new session: pass Cloudflare on the home page first
            page.goto(SITE + "/", wait_until="domcontentloaded", timeout=45000)
            _browser.pass_cloudflare(page, 30)
        for _ in range(2):
            got = _browser.capture(page, lambda: page.goto(url, wait_until="commit", timeout=45000),
                                   lambda u: "graphql" in u, timeout=12, body=lambda t: '"departing"' in t)
            if not got and _browser.pass_cloudflare(page, 30):  # challenged on the way: the page loads after
                got = _browser.capture(page, lambda: None, lambda u: "graphql" in u, timeout=15,
                                       body=lambda t: '"departing"' in t)
            if got:
                return got[-1][1]
        return ""

    txt = _browser.run(job, "allegiant", headful=True, timeout=150)
    if not txt:
        raise RuntimeError("allegiant: no flights response (Cloudflare or site change)")
    return json.loads(txt)


def search(q: SearchQuery) -> list[Itinerary]:
    pairs = _pairs(q.origins, q.destinations)
    if not pairs or not available():
        return []
    out: list[Itinerary] = []
    for o, d in pairs[:3]:
        url = deeplink(o, d, q.departure, q.return_date, q.adults)
        key = f"allegiant:{o}:{d}:{q.departure}:{q.return_date}:{q.adults}"
        if (data := cache.get(key)) is None:
            data = _fetch(url)
            cache.put(key, data)
        outs, backs = parse(data, q.adults)
        if q.return_date and not backs:
            continue
        out += combine(q, "allegiant", "Allegiant", outs, backs if q.return_date else None, "USD", url,
                       {"G4": "Allegiant"}, note="Allegiant fare incl. taxes and carrier charges; bags and seats extra.")
    return out
