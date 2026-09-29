"""Seller trust rules and itinerary warnings. The goal is to never present a
fare as simpler or safer than it really is."""

from __future__ import annotations

from datetime import timedelta

from .models import Itinerary, Trip

# Where a fare can be trusted to be the price you pay, with a company behind it
# that handles changes and refunds itself: the airline, Google Flights and ITA
# Matrix (which hand you to the airline or a seller you pick), and the largest
# booking sites (Expedia Group, Booking Holdings). Everything else is
# "unreliable" and hidden by default: agencies whose price often grows at
# checkout (Mytrip, Gotogate, eDreams, Opodo, Kiwi.com, Trip.com, EaseMyTrip,
# CheapOair...), hidden city fares (Skiplagged) and small agencies passed
# through by metasearch sites (HolidayBreakz, Magicfares...). Users can show
# them, flagged, with "*unreliable": "warn" in their seller rules (the
# Settings checkbox). Lower case, no ".com".
RELIABLE: set[str] = {
    # hand you to the airline or a seller you choose on their page
    "google flights", "ita matrix", "kayak", "momondo", "cheapflights", "skyscanner",
    # Expedia Group
    "expedia", "orbitz", "travelocity", "cheaptickets", "hotwire", "ebookers", "wotif",
    # Booking Holdings
    "priceline", "booking", "agoda",
}
SHOW_UNRELIABLE = "*unreliable"
# Sources whose every result is sold by an unreliable seller: not asked at all
# when those are hidden.
UNRELIABLE_SOURCES = {"kiwi", "kiwiweb", "skiplagged", "easemytrip", "gotogate", "mytrip", "tripcom", "edreams",
                      "opodo", "almosafer", "traveloka", "cleartrip", "ixigo", "omio"}


def _norm(name: str | None) -> str:
    n = (name or "").strip().lower()
    for suffix in (".com", ".co.uk", ".in"):
        n = n.removesuffix(suffix)
    return n


def reliable(seller: str | None, seller_kind: str | None = None) -> bool:
    """An airline, or a booking site on the reliable list."""
    if seller_kind == "airline":
        return True
    n = _norm(seller)
    if not n:  # unnamed agencies must not bypass the default seller filter
        return seller_kind != "ota"
    return n in RELIABLE or n.split(" (")[0] in RELIABLE


def show_unreliable(rules: dict[str, str] | None) -> bool:
    return any(k.lower() == SHOW_UNRELIABLE and v == "warn" for k, v in (rules or {}).items())


UNRELIABLE_WARNING = ("Sold by {seller}, not the airline or a major booking site. Its price can change at "
                      "checkout and support can be hard to reach. Check before paying.")


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


def _resell(t: Trip, tk: Itinerary, offer, cheapest: float) -> None:
    """The cheapest seller of a metasearch result is hidden, but a reliable
    one sells the same flights: show that one and its price instead. Offer
    prices are in the source's currency, so the ticket price scales by the
    ratio to the old cheapest offer."""
    old = tk.seller or ""
    tk.price = round(tk.price * offer.cheapest / cheapest, 2)
    tk.seller, tk.seller_kind = offer.seller, "airline" if offer.is_airline else "ota"
    if old:  # "Cheapest of 9 sites on KAYAK: TrustFares." no longer holds
        tk.warnings = [w for w in tk.warnings if old not in w]
        t.risks = [w for w in t.risks if old not in w]
    t.total_price = round(sum(x.price for x in t.tickets), 2)


def apply_rules(trips: list[Trip], rules: dict[str, str] | None) -> list[Trip]:
    """Drop trips containing blocked sellers and flag warned ones. Unreliable
    sellers are dropped unless the rules say "*unreliable": "warn"."""
    lower = {k.lower(): v for k, v in (rules or {}).items()}
    allow = show_unreliable(rules)
    out = []
    for t in trips:
        blocked = False
        for tk in t.tickets:
            # sellers listed by metasearch sites: only reliable ones unless asked
            if tk.offers:
                cheapest = min(o.cheapest for o in tk.offers)
                tk.offers = [o for o in tk.offers if (o.is_airline or reliable(o.seller) or allow)
                             and lower.get(o.seller.lower()) != "block"]
                if tk.offers and not allow and not reliable(tk.seller, tk.seller_kind) and cheapest > 0:
                    _resell(t, tk, min(tk.offers, key=lambda o: o.cheapest), cheapest)
            if not reliable(tk.seller, tk.seller_kind):
                if not allow:
                    blocked = True
                    continue
                msg = UNRELIABLE_WARNING.format(seller=tk.seller or "an unknown seller")
                if msg not in tk.warnings:
                    tk.warnings.append(msg)
            mode = lower.get((tk.seller or "").lower())
            if mode == "block":
                blocked = True
            elif mode == "warn" and reliable(tk.seller, tk.seller_kind):  # unreliable ones already say so
                msg = f"{tk.seller} is on your seller warning list."
                if msg not in tk.warnings:
                    tk.warnings.append(msg)
        if not blocked:
            out.append(t)
    return out
