"""Nok Air (DD, Thailand) direct from its own booking app (booking.nokair.com,
Sabre EzyCommerce). Thai domestic out of Don Mueang plus a few regional
routes (Yangon, Chennai, ...), thin on Google and Kiwi.

Plain HTTP JSON, no browser: see _c_ezycommerce.py for the public tenant key
(read from the booking page at runtime) and endpoints. One request per search
(a round trip is one request with both routes). About 2 seconds per search.

Prices: the fare ``price`` is per search incl. VAT and airport tax (the fare
object lists them: 2172.90 + 152.10 VAT + 130 airport tax = 2455 THB).
Verified September 2026: DMK-CNX 22 Oct 2026 DD120 2455.00 THB here and
"2,455.00" (NOK LITE) on the flight selection page, rendered headless.

Nok Air adds a connection fee (THB 500 to 900) only at the last booking step
for connecting itineraries, so we keep nonstop flights only. The network list
has bus and van transfer points with codes like "AM1"; those are skipped."""

from __future__ import annotations

import re

from ..models import Itinerary, SearchQuery
from . import _c_ezycommerce as ezy
from ._airline import combine, countries

EZY = ezy.Ezy("nokair", "https://booking.nokair.com")
NAMES = {"DD": "Nok Air"}
CURRENCY = "THB"
_IATA = re.compile(r"^[A-Z]{3}$")


def relevant(origins: list[str], destinations: list[str]) -> bool:
    net = EZY.network()
    if net is not None:
        return any(d in net.get(o, []) for o in origins for d in destinations if _IATA.match(d))
    return "TH" in countries(origins) | countries(destinations)


def deeplink(origin, dest, dep, ret=None, adults: int = 1) -> str:
    legs = [(origin, dest, dep)] + ([(dest, origin, ret)] if ret else [])
    return EZY.deeplink(legs, adults, CURRENCY)


def _nonstop(js: list[dict]) -> list[dict]:
    return [j for j in js if len(j["segments"]) == 1]


def search(q: SearchQuery) -> list[Itinerary]:
    if q.cabin != "economy" or not relevant(q.origins, q.destinations):
        return []
    out: list[Itinerary] = []
    pairs = [(o, d) for o in q.origins for d in q.destinations
             if o != d and _IATA.match(o) and _IATA.match(d) and EZY.has_route(o, d) is not False][:4]
    for o, d in pairs:
        legs = [(o, d, q.departure)] + ([(d, o, q.return_date)] if q.return_date else [])
        data = EZY.shop(legs, q.adults, CURRENCY)
        outs = _nonstop(ezy.parse(data, 0, q.cabin, q.departure))
        backs = _nonstop(ezy.parse(data, 1, q.cabin, q.return_date)) if q.return_date else None
        if not outs or (q.return_date and not backs):
            continue
        out += combine(q, "nokair", "Nok Air", outs, backs, data.get("currency") or CURRENCY,
                       deeplink(o, d, q.departure, q.return_date, q.adults), NAMES,
                       note="Nok Air cheapest fare incl. taxes (usually NOK LITE: 7 kg carry on only).")
    return out
