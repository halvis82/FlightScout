"""Optional paid fallback: SerpApi Google Flights. Enabled only when
SERPAPI_KEY is set (free tier is 250 searches a month)."""

from __future__ import annotations

import os
from datetime import datetime

import httpx

from ..models import Itinerary, SearchQuery, Segment, Slice

_CABIN = {"economy": 1, "premium": 2, "business": 3, "first": 4}


def enabled() -> bool:
    return bool(os.environ.get("SERPAPI_KEY"))


def search(q: SearchQuery) -> list[Itinerary]:
    if not enabled():
        return []
    params = {
        "engine": "google_flights", "api_key": os.environ["SERPAPI_KEY"],
        "departure_id": ",".join(q.origins), "arrival_id": ",".join(q.destinations),
        "outbound_date": q.departure.isoformat(), "currency": q.currency, "hl": "en",
        "type": 1 if q.return_date else 2, "travel_class": _CABIN[q.cabin], "adults": q.adults,
    }
    if q.return_date:
        params["return_date"] = q.return_date.isoformat()
    r = httpx.get("https://serpapi.com/search.json", params=params, timeout=60)
    r.raise_for_status()
    data = r.json()
    url = data.get("search_metadata", {}).get("google_flights_url")
    out = []
    for grp in ("best_flights", "other_flights"):
        for f in data.get(grp, []):
            if "price" not in f:
                continue
            segs = [Segment(
                origin=s["departure_airport"]["id"], destination=s["arrival_airport"]["id"],
                departure=datetime.strptime(s["departure_airport"]["time"], "%Y-%m-%d %H:%M"),
                arrival=datetime.strptime(s["arrival_airport"]["time"], "%Y-%m-%d %H:%M"),
                carrier=(s.get("flight_number") or "??").split()[0], carrier_name=s.get("airline"),
                flight_number=(s.get("flight_number") or "").split()[-1] or None,
                duration_min=s.get("duration"), aircraft=s.get("airplane"),
            ) for s in f["flights"]]
            out.append(Itinerary(
                source="serpapi", price=float(f["price"]), currency=q.currency,
                slices=[Slice(segments=segs, duration_min=f["total_duration"])],
                booking_url=url or "https://www.google.com/travel/flights",
                seller="Google Flights", seller_kind="metasearch",
            ))
    return out
