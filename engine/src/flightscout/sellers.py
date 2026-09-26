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
    "CheapOair": "warn",
    "OneTravel": "warn",
    "FlightHub": "warn",
    "Justfly": "warn",
    "Justfly.com": "warn",
}


# Booking sites and metasearch engines we have verified are established,
# real companies (public, licensed or long running, reachable support).
# Sellers that metasearch sites pass through (Wego, KAYAK, Aviasales...)
# include tiny or unknown agencies; anything not here and not an airline is
# "unverified": hidden by default, shown with a warning when a user asks for
# it ("*unverified": "warn" in their seller rules). Lower case, no ".com".
VERIFIED: set[str] = {
    # metasearch and our own sources
    "google flights", "ita matrix", "kayak", "momondo", "cheapflights", "skyscanner", "skiplagged", "wego",
    "aviasales", "ixigo",
    # Expedia Group, Booking Holdings
    "expedia", "orbitz", "travelocity", "hotwire", "cheaptickets", "ebookers", "wotif", "priceline", "booking",
    "agoda",
    # Trip.com Group, Kiwi, eDreams ODIGEO, Etraveli
    "trip", "tripcom", "ctrip", "kiwi", "edreams", "opodo", "go voyages", "travellink", "gotogate", "mytrip",
    "flightnetwork", "supersaver", "trip.ru",
    # Fareportal, FlightHub Group, Travix, Super
    "cheapoair", "onetravel", "flighthub", "justfly", "budgetair", "vayama", "super",
    # regional leaders (listed or long established)
    "almosafer", "easemytrip", "makemytrip", "goibibo", "yatra", "cleartrip", "paytm", "traveloka", "tiket",
    "airpaz", "wingie", "enuygun", "lastminute", "flight centre", "studentuniverse", "globehunters", "omio",
    "travelstart", "despegar", "decolar", "almundo",
    # checked 2026-09-26 and left out: Kiss&Fly (1.1/5, refund and "scam" reports), Travelgenio (1.5/5,
    # refunds withheld), HolidayBreakz (reports of calling after payment to demand more)
}


def _norm(name: str | None) -> str:
    n = (name or "").strip().lower()
    for suffix in (".com", ".co.uk", ".in"):
        n = n.removesuffix(suffix)
    return n


def verified(seller: str | None, seller_kind: str | None = None) -> bool:
    """An airline, or a booking site we know to be an established company."""
    if seller_kind == "airline":
        return True
    n = _norm(seller)
    if not n:  # no third party named: the source itself sells it, and every source is a verified company
        return True
    return n in VERIFIED or n.split(" (")[0] in VERIFIED


UNVERIFIED_WARNING = ("Sold by {seller}, an agency FlightScout couldn't verify as an established company. "
                      "Check its reviews and licensing before paying.")


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
    """Drop trips containing blocked sellers and flag warned ones. Unverified
    agencies are blocked unless the rules say "*unverified": "warn"."""
    rules = {**DEFAULT_RULES, **(rules or {})}
    lower = {k.lower(): v for k, v in rules.items()}
    show_unverified = lower.get("*unverified") == "warn"
    out = []
    for t in trips:
        blocked = False
        for tk in t.tickets:
            # agencies passed through by metasearch sites: only verified ones in offer lists
            if tk.offers:
                tk.offers = [o for o in tk.offers if o.is_airline or verified(o.seller) or show_unverified]
            if not verified(tk.seller, tk.seller_kind):
                if not show_unverified:
                    blocked = True
                    continue
                msg = UNVERIFIED_WARNING.format(seller=tk.seller or "an unknown seller")
                if msg not in tk.warnings:
                    tk.warnings.append(msg)
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
