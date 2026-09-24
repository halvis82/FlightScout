"""Airline directory (data/airlines.json) and deep links into each airline's
own search, pre-filled with a route when the airline supports it. Mirrors
web/src/lib/airlines.ts."""

from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from importlib import resources
from urllib.parse import quote

REGIONS = {
    "global": "Global networks", "nordics": "Nordics", "europe": "Europe", "us_domestic": "US domestic",
    "north_america": "Canada", "mexico": "Mexico", "central_america_caribbean": "Central America and Caribbean",
    "south_america": "South America", "middle_east": "Middle East", "africa": "Africa", "asia": "Asia",
    "oceania": "Oceania",
}
CATEGORIES = {
    "full_service": "Full service", "low_cost": "Low cost", "ultra_low_cost": "Ultra low cost",
    "hybrid": "Hybrid", "regional": "Regional", "premium_leisure": "Premium leisure",
}
_MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
_MON_SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


@lru_cache
def all_airlines() -> list[dict]:
    raw = resources.files("flightscout.data").joinpath("airlines.json").read_text("utf-8")
    return json.loads(raw)["airlines"]


def get(code: str) -> dict | None:
    code = code.upper()
    return next((a for a in all_airlines() if a["iata"] == code), None)


def find(query: str = "", region: str | None = None, category: str | None = None,
         alliance: str | None = None) -> list[dict]:
    q = query.strip().lower()
    out = []
    for a in all_airlines():
        if region and region not in a.get("regions", []):
            continue
        if category:
            cats = {"low_cost", "ultra_low_cost", "hybrid"} if category == "budget" else {category}
            if a.get("category") not in cats:
                continue
        if alliance and (a.get("alliance") or "none") != alliance:
            continue
        if q and not (q == a["iata"].lower() or q in a["name"].lower() or any(q in t.lower() for t in a.get("tags", []))):
            continue
        out.append(a)
    return out


def _fmt(d: date, f: str | None) -> str:
    if f == "YYYYMMDD":
        return d.strftime("%Y%m%d")
    if f == "MM/DD/YYYY":
        return d.strftime("%m/%d/%Y")
    if f == "DD/MM/YYYY":
        return d.strftime("%d/%m/%Y")
    if f == "DD.MM.YYYY":
        return d.strftime("%d.%m.%Y")
    if f == "MMM DD, YYYY":
        return quote(f"{_MON_SHORT[d.month - 1]} {d.day:02d}, {d.year}")
    return d.isoformat()


def link(a: dict, origin: str | None = None, destination: str | None = None, depart: date | None = None,
         ret: date | None = None, adults: int = 1) -> tuple[str, bool]:
    """(url, prefilled). Falls back to the airline's search page."""
    if not (origin and destination and depart) or not a.get("deeplink"):
        return a.get("search_url") or a.get("website"), False
    tpl = a["oneway_deeplink"] if (not ret and a.get("oneway_deeplink")) else a["deeplink"]
    f = a.get("date_format")
    vals = {
        "origin": origin.upper(), "destination": destination.upper(), "adults": str(adults),
        "depart": _fmt(depart, f), "return": _fmt(ret, f) if ret else "",
        "depart_mon": _MON[depart.month - 1], "depart_day": f"{depart.day:02d}",
        "return_mon": _MON[ret.month - 1] if ret else "", "return_day": f"{ret.day:02d}" if ret else "",
    }
    for k, v in vals.items():
        tpl = tpl.replace("{" + k + "}", v)
    return tpl, True
