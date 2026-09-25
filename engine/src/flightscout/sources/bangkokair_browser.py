"""Bangkok Airways (PG) direct from bangkokair.com through the shared headless
Chrome (see _browser.py). "Asia's boutique airline": Bangkok to Samui (which
it mostly owns), Chiang Mai, Phuket, Krabi and regional routes to Cambodia,
Laos and the Maldives.

The booking app (digital.bangkokair.com, Amadeus Digital Experience) sits
behind Imperva (Incapsula), so plain HTTP gets 403. The home page's search box
starts a booking with a form POST to digital.bangkokair.com/booking; we submit
the same form from the home page in headless Chrome and capture the
air-bounds JSON (see _des.py; a bare POST without the home page as referrer
gets "Access denied"). About 14 seconds per direction.

Prices: the air bound ``totalPrices.total`` is the price for all passengers
incl. taxes and fees (base 3,950 + taxes 130 + fees 100 = 4,180 THB).
Verified September 2026 (headless): BKK-USM 22 Oct 2026 PG171 THB 4,180
(PGPROMO) here and "Economy from THB 4,180" on the flight selection page;
PG121 THB 4,480 both. Round trips are two one way searches, priced the way the
site shows each direction."""

from __future__ import annotations

from datetime import date

from .. import fx
from ..models import Itinerary, SearchQuery
from . import _browser, _des
from ._airline import combine

SITE = "https://www.bangkokair.com/"
BOOK = "https://digital.bangkokair.com/booking?lang=en-GB"
NAMES = {"PG": "Bangkok Airways"}
# Bangkok Airways stations (its own network, 2026).
THAI = {"BKK", "USM", "CNX", "CEI", "HKT", "KBV", "LPT", "THS", "TDX", "UTP"}
STATIONS = THAI | {"KTI", "PNH", "SAI", "REP", "LPQ", "VTE", "MLE", "SIN", "HKG", "KUL", "RGN", "DAC"}
FAMILIES = ["PGREFXFLEX"]  # what the home page search box sends
FACTS = [{"key": "countrySite", "value": "THDESKTOP"}, {"key": "primaryPaxDetailsEditable", "value": True},
         {"key": "LANGUAGE", "value": "GB"}]
_CABINS = ("economy", "business")


def available() -> bool:
    return _browser.available()


def _pairs(origins: list[str], destinations: list[str]) -> list[tuple[str, str]]:
    return [(o, d) for o in origins for d in destinations
            if o != d and o in STATIONS and d in STATIONS and (o in THAI or d in THAI)]


def relevant(origins: list[str], destinations: list[str]) -> bool:
    return available() and bool(_pairs(origins, destinations))


def deeplink() -> str:
    """The booking app starts from a form POST, so there is no search URL:
    this opens the home page search box."""
    return SITE


def _bound(o: str, d: str, day: date, adults: int, cabin: str) -> tuple[list[dict], str | None]:
    return _des.parse(_des.fetch("bangkokair", SITE, BOOK, o, d, day, adults, FAMILIES, FACTS), cabin)


def search(q: SearchQuery) -> list[Itinerary]:
    if q.cabin not in _CABINS or not relevant(q.origins, q.destinations):
        return []
    out: list[Itinerary] = []
    for o, d in _pairs(q.origins, q.destinations)[:2]:
        outs, cur = _bound(o, d, q.departure, q.adults, q.cabin)
        backs, note = None, "Bangkok Airways cheapest fare family in the cabin, incl. taxes and fees."
        if q.return_date and outs:
            backs, c2 = _bound(d, o, q.return_date, q.adults, q.cabin)
            if backs and c2 and cur and c2 != cur:  # each side is priced in its origin's currency
                backs = [{**b, "total": round(fx.convert(b["total"], c2, cur), 2)} for b in backs]
                note += f" The return was priced in {c2} and converted to {cur}."
        if not outs or (q.return_date and not backs):
            continue
        out += combine(q, "bangkokair", "Bangkok Airways", outs, backs, cur or "THB", deeplink(), NAMES, note=note)
    return out
