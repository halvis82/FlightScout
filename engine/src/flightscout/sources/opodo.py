"""Opodo, eDreams ODIGEO's sister brand of eDreams: same platform and search
call (see edreams.py), its own prices and booking pages (opodo.co.uk, GBP)."""

from __future__ import annotations

from ..models import Itinerary, SearchQuery
from .edreams import available, relevant, search_brand  # noqa: F401


def search(q: SearchQuery) -> list[Itinerary]:
    return search_brand(q, "opodo")
