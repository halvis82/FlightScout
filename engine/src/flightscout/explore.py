"""Explore: cheapest places to go from an origin in a date window. Kiwi only
returns 15 itineraries per call, so we fan out over regions and countries
(broad by default, or the user's own list) and merge with Ryanair's fare
finder."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date

import logging

from . import airports, fx
from .models import Destination
from .sources import google_explore, kayak, kiwi, kiwiweb, ryanair

# Batches the web UI requests one after another so the map fills in quickly:
# broad first, then depth.
BATCHES = [
    ["anywhere", "Europe", "North America", "Asia", "South America", "Mexico", "United States"],
    ["Africa", "Oceania", "Central America", "Caribbean", "Middle East", "Canada", "Japan", "Thailand"],
    ["Spain", "Italy", "Portugal", "Greece", "France", "United Kingdom", "Germany", "Poland",
     "Croatia", "Turkey", "Iceland", "Morocco"],
    ["Brazil", "Colombia", "Peru", "Argentina", "Chile", "Costa Rica", "Dominican Republic", "Cuba",
     "Puerto Rico", "Jamaica", "Panama", "Guatemala", "Hawaii", "Alaska"],
    ["Netherlands", "Belgium", "Switzerland", "Austria", "Czechia", "Hungary", "Ireland", "Denmark",
     "Sweden", "Norway", "Finland", "Romania", "Bulgaria", "Montenegro", "Albania", "Cyprus", "Malta"],
    ["Philippines", "Vietnam", "Indonesia", "Malaysia", "Singapore", "South Korea", "China", "India",
     "Sri Lanka", "Egypt", "Jordan", "United Arab Emirates", "Kenya", "South Africa", "Tanzania",
     "Australia", "New Zealand"],
]

log = logging.getLogger(__name__)

DEFAULT_REGIONS = [
    "anywhere", "Europe", "North America", "South America", "Asia", "Africa", "Oceania",
    "Central America", "Caribbean", "Middle East",
    "Spain", "Italy", "Portugal", "Greece", "France", "United Kingdom", "Germany", "Poland",
    "Croatia", "Turkey", "Iceland", "United States", "Mexico", "Canada", "Japan", "Thailand",
    "Morocco",
]


def explore(origin: str, start: date, end: date, currency: str = "USD",
            nights: tuple[int, int] | None = None, sources: list[str] | None = None,
            regions: list[str] | None = None) -> tuple[list[Destination], dict[str, str]]:
    sources = sources or ["google", "kiwi", "kiwiweb", "kayak", "ryanair"]
    regions = regions or DEFAULT_REGIONS
    origins = airports.expand(origin)
    jobs = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        if "kiwi" in sources:
            # Kiwi takes one place per call (a comma list gets misread), and it
            # resolves an airport to its city, so query each origin up to two.
            for o in origins[:2]:
                for r in regions:
                    jobs.append((f"kiwi:{o}:{r}", ex.submit(kiwi.explore, o, start, end, currency, nights, r)))
        # Google Explore (real browser): broad and fast when available. Only on
        # the first batch; it picks its own dates (week long trips).
        if "google" in sources and google_explore.available() and "anywhere" in regions:
            for o in origins[:2]:
                jobs.append((f"google:{o}", ex.submit(google_explore.explore, o, currency)))
        # Kiwi's web backend (one cheapest trip per city, ~80 cities per call)
        # and KAYAK Explore (cached fares, 100+ places per call) are global,
        # not per region, so they run once, with the batch that asks "anywhere".
        if "anywhere" in regions:
            if "kiwiweb" in sources:
                jobs.append(("kiwiweb:" + ",".join(origins[:4]),
                             ex.submit(kiwiweb.explore, origins[:4], start, end, currency, nights)))
            if "kayak" in sources:
                for o in origins[:2]:
                    jobs.append((f"kayak:{o}", ex.submit(kayak.explore, o, start, end, currency, nights)))
        if "ryanair" in sources and not nights:
            for o in origins[:3]:
                jobs.append((f"ryanair:{o}", ex.submit(ryanair.explore, o, start, end, currency)))
        found, failed = [], {}
        for name, f in jobs:
            try:
                found.extend(f.result())
            except Exception as e:
                src = name.split(":")[0]
                failed.setdefault(src, []).append(name.split(":", 1)[1])
                log.debug("explore %s failed: %s", name, e)
    # One short line per source instead of a wall of raw errors.
    errors = {src: f"{len(parts)} of {sum(1 for n, _ in jobs if n.startswith(src))} lookups failed"
              for src, parts in failed.items()}
    best: dict[str, Destination] = {}
    for d in found:
        if d.destination in origins:
            continue
        if d.currency.upper() != currency.upper():
            d.price = round(fx.convert(d.price, d.currency, currency), 2)
            d.currency = currency.upper()
        if d.destination not in best or d.price < best[d.destination].price:
            best[d.destination] = d
    return sorted(best.values(), key=lambda d: d.price), errors
