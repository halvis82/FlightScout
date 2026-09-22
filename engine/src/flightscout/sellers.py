"""Seller trust rules and itinerary warnings. The goal is to never present a
fare as simpler or safer than it really is."""

from __future__ import annotations

from datetime import timedelta

from .models import Itinerary, Trip

# Sellers with a track record of hard to reach support, fare changes after
# purchase or aggressive add ons. Shown with a warning by default; users can
# change any of these to "block" or remove them.
DEFAULT_RULES: dict[str, str] = {
    "Kiwi.com": "warn",
    "Gotogate": "warn",
    "Mytrip": "warn",
    "Flightnetwork": "warn",
    "Trip.com": "warn",
    "eDreams": "warn",
    "Opodo": "warn",
    "Budgetair": "warn",
    "Travelgenio": "warn",
    "Kissandfly": "warn",
    "Fly.com": "warn",
}


def annotate(it: Itinerary) -> Itinerary:
    """Add structural warnings that don't depend on who sells the ticket."""
    w = list(it.warnings)
    for sl in it.slices:
        for a, b in zip(sl.segments, sl.segments[1:]):
            gap = b.departure - a.arrival
            if a.destination != b.origin:
                w.append(f"Airport change at {a.destination} to {b.origin} during a connection.")
            if it.self_transfer and gap < timedelta(hours=3):
                w.append(f"Only {int(gap.total_seconds() // 60)} min to self transfer at {a.destination}.")
            elif gap < timedelta(minutes=45):
                w.append(f"Tight {int(gap.total_seconds() // 60)} min connection at {a.destination}.")
            if gap > timedelta(hours=8) and a.arrival.date() != b.departure.date():
                w.append(f"Overnight layover at {a.destination} ({gap.total_seconds() / 3600:.0f} h).")
    it.warnings = list(dict.fromkeys(w))
    return it


def apply_rules(trips: list[Trip], rules: dict[str, str] | None) -> list[Trip]:
    """Drop trips containing blocked sellers and flag warned ones."""
    rules = {**DEFAULT_RULES, **(rules or {})}
    lower = {k.lower(): v for k, v in rules.items()}
    out = []
    for t in trips:
        blocked = False
        for tk in t.tickets:
            mode = lower.get((tk.seller or "").lower())
            if mode == "block":
                blocked = True
            elif mode == "warn":
                msg = f"{tk.seller} is on your seller warning list."
                if msg not in tk.warnings:
                    tk.warnings.append(msg)
        if not blocked:
            out.append(t)
    return out
