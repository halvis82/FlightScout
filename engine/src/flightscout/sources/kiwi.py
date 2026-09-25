"""Kiwi.com through its public MCP endpoint (https://mcp.kiwi.com, keyless).
Kiwi is the main source of self transfer (virtual interlining) fares, flexible
date ranges and "anywhere" exploration."""

from __future__ import annotations

import json
import random
import threading
import time
from datetime import date, datetime

import httpx

from .. import airports, cache
from ..models import Destination, Itinerary, SearchQuery, Segment, Slice

URL = "https://mcp.kiwi.com"
_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
_CABIN = {"economy": "M", "premium": "W", "business": "C", "first": "F"}

KIWI_WARNING = (
    "Sold by Kiwi.com (online travel agency). Connections between different airlines "
    "are usually separate tickets protected only by the Kiwi Guarantee, not by the airlines."
)


def _parse_sse(text: str) -> dict:
    for line in text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:])
    return json.loads(text)


# Kiwi answers bursts with 503s, so cap concurrency and retry with backoff.
_slots = threading.BoundedSemaphore(4)
_RETRY = {429, 500, 502, 503, 504}


class KiwiUnavailable(RuntimeError):
    pass


def _call(args: dict) -> dict:
    key = "kiwi:" + json.dumps(args, sort_keys=True)
    if (hit := cache.get(key)) is not None:
        return hit
    last: Exception | None = None
    for attempt in range(4):
        try:
            with _slots:
                data = _call_once(args)
            cache.put(key, data)
            return data
        except httpx.HTTPStatusError as e:
            last = e
            if e.response.status_code not in _RETRY:
                raise
        except (httpx.TransportError, json.JSONDecodeError) as e:
            last = e
        time.sleep(min(8, 0.8 * 2 ** attempt) + random.random() * 0.5)
    raise KiwiUnavailable(f"Kiwi.com did not respond ({type(last).__name__})")


def _call_once(args: dict) -> dict:
    with httpx.Client(timeout=90) as c:
        init = c.post(URL, headers=_HEADERS, json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "flightscout", "version": "0.1"}},
        })
        init.raise_for_status()
        h = dict(_HEADERS)
        if sid := init.headers.get("mcp-session-id"):
            h["mcp-session-id"] = sid
        c.post(URL, headers=h, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        r = c.post(URL, headers=h, json={
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "search-flight", "arguments": args},
        })
        r.raise_for_status()
    msg = _parse_sse(r.text)
    if "error" in msg:
        raise RuntimeError(f"kiwi: {msg['error']}")
    res = msg["result"]
    if res.get("isError"):
        raise RuntimeError("kiwi: " + " ".join(c.get("text", "") for c in res.get("content", []))[:300])
    return json.loads(res["content"][0]["text"])


def _d(x: date) -> str:
    return x.strftime("%d/%m/%Y")


def _flight_no(num, carrier: str | None) -> str | None:
    """Kiwi sometimes prefixes the carrier ("H2H2270"); keep just the number
    so the same flight matches across sources."""
    n = str(num or "").strip()
    if carrier and n.upper().startswith(carrier.upper()):
        n = n[len(carrier):]
    return n or None


def _slice(leg: dict) -> Slice:
    segs = [
        Segment(
            origin=s["from"], destination=s["to"],
            departure=datetime.fromisoformat(s["departureTime"]) if s.get("departureTime") else datetime.fromisoformat(leg["departureTime"]),
            arrival=datetime.fromisoformat(s["arrivalTime"]) if s.get("arrivalTime") else datetime.fromisoformat(leg["arrivalTime"]),
            carrier=s.get("carrier") or "??", carrier_name=s.get("carrierName"),
            flight_number=_flight_no(s.get("flightNumber"), s.get("carrier")),
            duration_min=(s["durationSeconds"] // 60) if s.get("durationSeconds") else None,
        )
        for s in leg["segments"]
    ]
    return Slice(segments=segs, duration_min=leg["durationSeconds"] // 60)


def _itins(data: dict) -> list[Itinerary]:
    out = []
    for it in data.get("itineraries", []):
        slices = [_slice(it["outbound"])]
        if it.get("inbound"):
            slices.append(_slice(it["inbound"]))
        multi_carrier = any(len({s.carrier for s in sl.segments}) > 1 for sl in slices)
        out.append(Itinerary(
            source="kiwi", price=float(it["price"]), currency=data.get("currency", "EUR"),
            slices=slices, booking_url=it["bookingUrl"], seller="Kiwi.com", seller_kind="ota",
            self_transfer=multi_carrier, baggage=it.get("baggage"),
            warnings=[KIWI_WARNING] if multi_carrier else [
                "Sold by Kiwi.com (online travel agency), not the airline."],
        ))
    return out


def search(q: SearchQuery) -> list[Itinerary]:
    # Kiwi takes one place per side; query each origin/destination pair
    # (metro expansion is kept small by the caller). A call takes ~10 s on
    # Kiwi's side, so pairs run in parallel (bounded by _slots).
    calls: list[dict] = []
    for o in q.origins[:3]:
        for d in q.destinations[:3]:
            args = {
                "flyFrom": o, "flyTo": d, "departureDate": _d(q.departure),
                "departureDateFlexDays": min(q.departure_flex_days, 10),
                "adults": q.adults, "cabinClass": _CABIN[q.cabin],
                "currency": q.currency, "locale": "en",
            }
            if q.return_date:
                args["returnDate"] = _d(q.return_date)
                args["returnDateFlexDays"] = min(q.return_flex_days, 10)
            calls.append(args)
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=len(calls) or 1) as ex:
        out: list[Itinerary] = [i for data in ex.map(_call, calls) for i in _itins(data)]
    if q.max_stops is not None:
        out = [i for i in out if all(s.stops <= q.max_stops for s in i.slices)]
    return out


def search_range(origin: str, destination: str, start: date, end: date, currency: str,
                 nights: tuple[int, int] | None = None, cabin: str = "economy") -> list[Itinerary]:
    """Cheapest itineraries anywhere in a departure window. With ``nights`` it
    searches round trips of that length. One request, up to 15 results."""
    args = {
        "flyFrom": origin, "flyTo": destination, "departureDate": _d(start),
        "departureDateTo": _d(end), "currency": currency, "locale": "en",
        "cabinClass": _CABIN[cabin],
    }
    if nights:
        args["nights_in_dst_from"], args["nights_in_dst_to"] = nights
    return _itins(_call(args))


def explore(origin: str, start: date, end: date, currency: str,
            nights: tuple[int, int] | None = None, to: str = "anywhere") -> list[Destination]:
    """``to`` may be "anywhere", a region ("Europe", "North America") or a
    country ("Mexico"). Each call returns up to 15 itineraries."""
    out = []
    for it in search_range(origin, to, start, end, currency, nights):
        dest = it.slices[0].destination
        ap = airports.get(dest)
        out.append(Destination(
            origin=origin, destination=dest, city=ap.city if ap else None,
            country=ap.country if ap else None, price=it.price, currency=it.currency,
            departure=it.slices[0].departure.date(),
            return_date=it.slices[1].departure.date() if len(it.slices) > 1 else None,
            source="kiwi", booking_url=it.booking_url,
            lat=ap.lat if ap else None, lon=ap.lon if ap else None,
        ))
    return out
