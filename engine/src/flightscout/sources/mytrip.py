"""Mytrip, Etraveli Group's sister brand of Gotogate: same backend and
GraphQL endpoint (see gotogate.py), its own prices and booking pages."""

from __future__ import annotations

from ..models import Itinerary, SearchQuery
from .gotogate import relevant, search_brand  # noqa: F401


def search(q: SearchQuery) -> list[Itinerary]:
    return search_brand(q, "mytrip")
