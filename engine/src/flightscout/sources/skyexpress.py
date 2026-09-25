"""SKY express (GQ, Greece) direct from its own booking app
(flights.skyexpress.gr, Sabre EzyCommerce). Kiwi and Google carry SKY express
only partly (Greek domestic and island hops are thin there), so its own fares
fill a real gap.

Plain HTTP JSON, no browser: see _c_ezycommerce.py for the public tenant key
and endpoints. One request per search (a round trip is one request with both
routes, priced the way the site prices it). About 2 seconds per search. The
cheapest fare family per flight is usually SKYjoy (8 kg hand luggage only).
Verified September 2026: ATH-HER 22 Oct 2026 GQ210 48.62 EUR here and
"€ 48.62" on the flight selection page."""

from __future__ import annotations

from .. import airports
from ..models import Itinerary, SearchQuery
from . import _c_ezycommerce as ezy
from ._airline import combine

EZY = ezy.Ezy("skyexpress", "https://flights.skyexpress.gr")
NAMES = {"GQ": "SKY express"}
# Fallback gate when the network list is unavailable: every SKY express route
# touches Greece or Cyprus.
HOME = {"GR", "CY"}


def relevant(origins: list[str], destinations: list[str]) -> bool:
    net = EZY.network()
    if net is not None:
        return any(d in net.get(o, []) for o in origins for d in destinations)
    cc = {a.country for c in origins + destinations if (a := airports.get(c))}
    return bool(cc & HOME)


def deeplink(origin, dest, dep, ret=None, adults: int = 1, currency: str = "EUR") -> str:
    legs = [(origin, dest, dep)] + ([(dest, origin, ret)] if ret else [])
    return EZY.deeplink(legs, adults, currency)


def search(q: SearchQuery) -> list[Itinerary]:
    if not relevant(q.origins, q.destinations):
        return []
    cur = "EUR"
    out: list[Itinerary] = []
    pairs = [(o, d) for o in q.origins for d in q.destinations if o != d and EZY.has_route(o, d) is not False][:4]
    for o, d in pairs:
        legs = [(o, d, q.departure)] + ([(d, o, q.return_date)] if q.return_date else [])
        data = EZY.shop(legs, q.adults, cur)
        outs = ezy.parse(data, 0, q.cabin, q.departure)
        backs = ezy.parse(data, 1, q.cabin, q.return_date) if q.return_date else None
        if not outs or (q.return_date and not backs):
            continue
        out += combine(q, "skyexpress", "SKY express", outs, backs, data.get("currency") or cur,
                       deeplink(o, d, q.departure, q.return_date, q.adults, cur), NAMES,
                       note="SKY express cheapest fare family (usually SKYjoy: hand luggage only).")
    return out
