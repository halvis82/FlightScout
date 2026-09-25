"""Philippine Airlines (PR) direct from philippineairlines.com through the
shared headless Chrome (see _browser.py). Flag carrier of the Philippines:
domestic out of Manila and Cebu plus Asia, Australia, the Middle East and
North America.

The booking app (booking.philippineairlines.com) is Amadeus Digital
Experience behind Imperva. The home page's booking box posts the search to it
(commercial fare family "PRECO" for economy, portal fact countryCode of the
origin); we submit the same form from the home page and capture the
air-bounds JSON (see _des.py). About 18 seconds per direction.

Prices: ``totalPrices.total`` for all passengers. The page says fares are
"ALL-IN ... INCLUDE government taxes and surcharges EXCEPT Philippine Travel
Tax", which only Philippine residents pay on international departures from
the Philippines (a warning says so on those). Verified September 2026
(headless): MNL-CEB 22 Oct 2026 PR1841 PHP 2,795 here and "From PHP 2,795"
on the flight selection page; the day's cheapest, PR1863, PHP 2,235 both.
Round trips are two one way searches."""

from __future__ import annotations

from datetime import date

from .. import fx
from ..models import Itinerary, SearchQuery
from . import _browser, _des
from ._airline import combine, countries

SITE = "https://www.philippineairlines.com/"
BOOK = "https://booking.philippineairlines.com/booking?lang=en-GB&"
NAMES = {"PR": "Philippine Airlines"}
_FAMILY = {"economy": "PRECO", "business": "PRBUS"}


def available() -> bool:
    return _browser.available()


def relevant(origins: list[str], destinations: list[str]) -> bool:
    """Every Philippine Airlines route touches the Philippines."""
    return available() and ("PH" in countries(origins) or "PH" in countries(destinations))


def deeplink() -> str:
    """The booking app starts from a form POST: this opens the home page."""
    return SITE


def _bound(o: str, d: str, day: date, adults: int, cabin: str) -> tuple[list[dict], str | None]:
    cc = next(iter(countries([o])), "PH")
    data = _des.fetch("philippineairlines", SITE, BOOK, o, d, day, adults, [_FAMILY[cabin]],
                      [{"key": "countryCode", "value": cc}])
    return _des.parse(data, cabin)


def search(q: SearchQuery) -> list[Itinerary]:
    if q.cabin not in _FAMILY or not relevant(q.origins, q.destinations):
        return []
    out: list[Itinerary] = []
    pairs = [(o, d) for o in q.origins for d in q.destinations
             if o != d and "PH" in countries([o]) | countries([d])][:2]
    for o, d in pairs:
        outs, cur = _bound(o, d, q.departure, q.adults, q.cabin)
        backs, c2 = _bound(d, o, q.return_date, q.adults, q.cabin) if q.return_date and outs else (None, None)
        if not outs or (q.return_date and not backs):
            continue
        note = "Philippine Airlines cheapest fare family in the cabin, incl. taxes and surcharges."
        if backs and c2 and cur and c2 != cur:  # each side is priced in its origin's currency
            backs = [{**b, "total": round(fx.convert(b["total"], c2, cur), 2)} for b in backs]
            note += f" The return was priced in {c2} and converted to {cur}."
        intl_from_ph = countries([o]) == {"PH"} and countries([d]) != {"PH"}
        if intl_from_ph:
            note += " Philippine residents also pay the Philippine Travel Tax, not included."
        out += combine(q, "philippineairlines", "Philippine Airlines", outs, backs, cur or "PHP", deeplink(),
                       NAMES, note=note)
    return out
