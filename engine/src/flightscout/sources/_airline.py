"""Small helpers shared by the direct airline sources that return one way
journeys: normalized journey dicts in, Itineraries out.

A journey dict is ``{"segments": [seg, ...], "total": float, "seats": int | None}``
where ``total`` is the price for all passengers incl. taxes and mandatory fees
and each seg is ``{"origin", "destination", "departure", "arrival", "carrier",
"number", "duration"?}`` with ISO times (local wall clock, an UTC offset is
allowed and used for exact durations)."""

from __future__ import annotations

from datetime import datetime

from .. import airports
from ..models import Itinerary, SearchQuery, Segment, Slice


def countries(codes: list[str]) -> set[str]:
    return {a.country for c in codes if (a := airports.get(c))}


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def make_slice(j: dict, names: dict[str, str] | None = None) -> Slice:
    names = names or {}
    segs = []
    for s in j["segments"]:
        dep, arr = _dt(s["departure"]), _dt(s["arrival"])
        dur = s.get("duration")
        if dur is None and dep.tzinfo and arr.tzinfo:
            dur = int((arr - dep).total_seconds() // 60)
        segs.append(Segment(
            origin=s["origin"], destination=s["destination"],
            departure=dep.replace(tzinfo=None), arrival=arr.replace(tzinfo=None),
            carrier=s["carrier"], carrier_name=names.get(s["carrier"]),
            flight_number=str(s["number"]) if s.get("number") not in (None, "", "None") else None,
            duration_min=dur, aircraft=s.get("aircraft"),
        ))
    first, last = _dt(j["segments"][0]["departure"]), _dt(j["segments"][-1]["arrival"])
    if j.get("duration"):
        total = int(j["duration"])
    elif first.tzinfo and last.tzinfo:
        total = int((last - first).total_seconds() // 60)
    else:  # local times on both ends: approximate, like the other sources
        total = int((last.replace(tzinfo=None) - first.replace(tzinfo=None)).total_seconds() // 60)
    return Slice(segments=segs, duration_min=max(total, 1))


def combine(q: SearchQuery, source: str, seller: str, outs: list[dict], backs: list[dict] | None,
            currency: str, url: str, names: dict[str, str] | None = None, note: str | None = None,
            limit: int = 6) -> list[Itinerary]:
    """Outbound x return (each already priced on its own, the way these
    airlines sell round trips) into Itineraries, cheapest ``limit`` per side."""
    if q.max_stops is not None:
        outs = [x for x in outs if len(x["segments"]) - 1 <= q.max_stops]
        if backs is not None:
            backs = [x for x in backs if len(x["segments"]) - 1 <= q.max_stops]
    outs = sorted(outs, key=lambda x: x["total"])[:limit]
    pairs = [None] if backs is None else sorted(backs, key=lambda x: x["total"])[:limit]
    out: list[Itinerary] = []
    for a in outs:
        for b in pairs:
            if backs is not None and b is None:
                continue
            warn = []
            if any(x and x.get("seats") and x["seats"] <= 3 for x in (a, b)):
                warn.append(f"Only a few seats left at this {seller} fare.")
            if note:
                warn.append(note)
            out.append(Itinerary(
                source=source, price=round(a["total"] + (b["total"] if b else 0), 2), currency=currency,
                slices=[make_slice(a, names)] + ([make_slice(b, names)] if b else []),
                booking_url=url, seller=seller, seller_kind="airline", warnings=warn,
            ))
    return out
