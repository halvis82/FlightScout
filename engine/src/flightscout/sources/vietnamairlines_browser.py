"""Vietnam Airlines (VN) direct from vietnamairlines.com through the shared
headless Chrome (see _browser.py). Vietnam's flag carrier (with its Pacific
Airlines arm): the dense domestic network plus Asia, Europe, Australia and the
US.

The booking app (booking.vietnamairlines.com) is Amadeus Digital Experience.
The home page's search box posts the search to it (commercial fare family
"WEB", portal facts country and language); we submit the same form from the
home page and capture the air-bounds JSON (see _des.py). About 20 seconds per
direction. Point of sale US, so prices come in USD.

Prices: ``totalPrices.total`` for all passengers incl. taxes, fees and carrier
surcharges (the page: "Below Fares include taxes and fees"). Verified September
2026 (headless): SGN-HAN 22 Oct 2026 VN6002 (operated by Pacific Airlines)
USD 96.30 and VN220 USD 100.60 here and "Economy from USD 96.30" / "from USD
100.60" on the flight selection page. Round trips are two one way searches."""

from __future__ import annotations

from datetime import date

from ..models import Itinerary, SearchQuery
from . import _browser, _des
from ._airline import combine, countries

SITE = "https://www.vietnamairlines.com/us/en"
BOOK = "https://booking.vietnamairlines.com/booking/availability/0?lang=en"
NAMES = {"VN": "Vietnam Airlines", "BL": "Pacific Airlines"}
FAMILIES = ["WEB"]
FACTS = [{"key": "countryCode", "value": "US"}, {"key": "language", "value": "en"}]
_CABINS = ("economy", "business")


def available() -> bool:
    return _browser.available()


def relevant(origins: list[str], destinations: list[str]) -> bool:
    """Every Vietnam Airlines route touches Vietnam."""
    return available() and ("VN" in countries(origins) or "VN" in countries(destinations))


def deeplink() -> str:
    """The booking app starts from a form POST: this opens the home page."""
    return SITE


def _bound(o: str, d: str, day: date, adults: int, cabin: str) -> tuple[list[dict], str | None]:
    return _des.parse(_des.fetch("vietnamairlines", SITE, BOOK, o, d, day, adults, FAMILIES, FACTS), cabin)


def search(q: SearchQuery) -> list[Itinerary]:
    if q.cabin not in _CABINS or not relevant(q.origins, q.destinations):
        return []
    out: list[Itinerary] = []
    pairs = [(o, d) for o in q.origins for d in q.destinations
             if o != d and "VN" in countries([o]) | countries([d])][:2]
    for o, d in pairs:
        outs, cur = _bound(o, d, q.departure, q.adults, q.cabin)
        backs = _bound(d, o, q.return_date, q.adults, q.cabin)[0] if q.return_date and outs else None
        if not outs or (q.return_date and not backs):
            continue
        out += combine(q, "vietnamairlines", "Vietnam Airlines", outs, backs, cur or "USD", deeplink(), NAMES,
                       note="Vietnam Airlines cheapest fare family in the cabin, incl. taxes and fees.")
    return out
