"""Optional paid fallback: SearchAPI.io's Google Flights API. Used only when
Google blocks our own requests (rate limited) and SEARCHAPI_KEY is set.
Pricing: 100 free requests, then from $40 for 10k (searchapi.io)."""

from __future__ import annotations

import os
from datetime import datetime

import httpx

from ..models import Itinerary, SearchQuery, Segment, Slice

_CABIN = {"economy": "economy", "premium": "premium_economy", "business": "business", "first": "first_class"}


def enabled() -> bool:
    return bool(os.environ.get("SEARCHAPI_KEY"))


def _when(ap: dict) -> datetime:
    if ap.get("date") and ap.get("time"):
        return datetime.strptime(f"{ap['date']} {ap['time']}", "%Y-%m-%d %H:%M")
    return datetime.strptime(ap["time"], "%Y-%m-%d %H:%M")


def search(q: SearchQuery) -> list[Itinerary]:
    if not enabled():
        return []
    params = {
        "engine": "google_flights", "api_key": os.environ["SEARCHAPI_KEY"],
        "departure_id": ",".join(q.origins), "arrival_id": ",".join(q.destinations),
        "outbound_date": q.departure.isoformat(), "currency": q.currency, "hl": "en", "gl": "us",
        "flight_type": "round_trip" if q.return_date else "one_way",
        "travel_class": _CABIN.get(q.cabin, "economy"), "adults": q.adults,
    }
    if q.return_date:
        params["return_date"] = q.return_date.isoformat()
    r = httpx.get("https://www.searchapi.io/api/v1/search", params=params, timeout=60)
    r.raise_for_status()
    data = r.json()
    link = (data.get("search_metadata") or {}).get("request_url") or "https://www.google.com/travel/flights"
    out = []
    for grp in ("best_flights", "other_flights"):
        for f in data.get(grp) or []:
            if not f.get("price") or not f.get("flights"):
                continue
            segs = []
            for s in f["flights"]:
                num = (s.get("flight_number") or "").split()
                segs.append(Segment(
                    origin=s["departure_airport"]["id"], destination=s["arrival_airport"]["id"],
                    departure=_when(s["departure_airport"]), arrival=_when(s["arrival_airport"]),
                    carrier=num[0] if num else "??", carrier_name=s.get("airline"),
                    flight_number=num[-1] if len(num) > 1 else None, duration_min=s.get("duration"),
                    aircraft=s.get("airplane"),
                ))
            out.append(Itinerary(
                source="serpapi", price=float(f["price"]), currency=q.currency,
                slices=[Slice(segments=segs, duration_min=f.get("total_duration") or sum(x.duration_min or 0 for x in segs))],
                booking_url=link, seller="Google Flights", seller_kind="metasearch",
                return_pending=bool(q.return_date),
            ))
    return out
