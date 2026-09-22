"""Explore: cheapest places to go from an origin in a date window. Kiwi only
returns 15 itineraries per call, so we fan out over regions and countries
(broad by default, or the user's own list) and merge with Ryanair's fare
finder."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date

from . import airports, fx
from .models import Destination
from .sources import kiwi, ryanair

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
    sources = sources or ["kiwi", "ryanair"]
    regions = regions or DEFAULT_REGIONS
    origins = airports.expand(origin)
    jobs = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        if "kiwi" in sources:
            # Kiwi resolves an airport to its city, so one origin is enough.
            for r in regions:
                jobs.append((f"kiwi:{r}", ex.submit(kiwi.explore, origins[0], start, end, currency, nights, r)))
        if "ryanair" in sources and not nights:
            for o in origins[:3]:
                jobs.append((f"ryanair:{o}", ex.submit(ryanair.explore, o, start, end, currency)))
        found, errors = [], {}
        for name, f in jobs:
            try:
                found.extend(f.result())
            except Exception as e:
                errors[name] = str(e)[:200]
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
