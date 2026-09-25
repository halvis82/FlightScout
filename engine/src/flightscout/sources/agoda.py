"""Agoda Flights (flights.agoda.com): a KAYAK white label on KAYAK's own
search backend (same results page, same CSRF ``formtoken``, same
/i/api/search/dynamic/flights/poll answer), so it reuses kayakweb's fetch
and parser under its own brand. Keyless, plain HTTP with Chrome TLS, 3
requests and 5 to 12 seconds per route. Every result carries each
provider's live price (airlines and OTAs); the Itinerary is the cheapest one,
the rest are in ``offers``. Prices in USD (the only market this host serves),
exactly what the Agoda results page shows.

Unofficial: fails soft."""

from __future__ import annotations

from ..models import Itinerary, SearchQuery
from . import kayakweb

kayakweb.BRANDS.setdefault("agoda", {"name": "Agoda", "path": "flights", "domains": {"USD": "flights.agoda.com"}})


def relevant(origins: list[str], destinations: list[str]) -> bool:
    return True


def search(q: SearchQuery) -> list[Itinerary]:
    return kayakweb.search_brand("agoda", q)
