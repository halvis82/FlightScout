"""MCP server exposing FlightScout to AI agents. Results are saved to the
user's web account when the CLI is logged in, so an agent's findings appear
in the browser (History page)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from mcp.server.mcpserver import MCPServer

from . import airports, config
from .client import Client

mcp = MCPServer(
    "flightscout",
    instructions=(
        "Flight search and planning. Use `search_flights` for normal itineraries, `plan_routes` to find "
        "cheaper split ticket, stopover and nested round trip routes via hubs, `build_trip` for multi city "
        "trips, `explore_destinations` for cheap places to go, `price_calendar` for cheapest dates, and the "
        "watchlist tools to track prices. Always show users the booking_url for each ticket and mention "
        "warnings (self transfer, separate tickets, OTA sellers). Prices are live and change quickly."
    ),
)


def _save(kind: str, query: dict, payload: dict) -> None:
    c = Client()
    if c.ready and c.token:
        try:
            c.save_result(kind, query, payload, origin="mcp")
        except Exception:
            pass


def _cur(c: str | None) -> str:
    return (c or config.load().get("currency") or "USD").upper()


def _compact(trips: list[dict], limit: int) -> list[dict]:
    """Trim the payload for the model's context: keep what matters to decide
    and to book."""
    out = []
    for t in trips[:limit]:
        out.append({
            "kind": t["kind"], "total_price": t["total_price"], "currency": t["currency"],
            "route": "-".join(t["route"]), "departure": t["departure"], "arrival": t["arrival"],
            "travel_hours": round(t["travel_min"] / 60, 1),
            "savings_vs_direct": t.get("savings_vs_direct"),
            "note": t.get("note"),
            "stopovers": t.get("stopovers"),
            "risks": t.get("risks", [])[:4],
            "tickets": [{
                "price": tk["price"], "source": tk["source"], "seller": tk.get("seller"),
                "self_transfer": tk.get("self_transfer"), "booking_url": tk["booking_url"],
                "slices": [{
                    "from": sl["origin"], "to": sl["destination"], "departure": sl["departure"],
                    "arrival": sl["arrival"], "stops": sl["stops"],
                    "flights": [f"{s['carrier']}{s.get('flight_number') or ''} {s['origin']}-{s['destination']}"
                                for s in sl["segments"]],
                } for sl in tk["slices"]],
            } for tk in t["tickets"]],
        })
    return out


@mcp.tool()
def search_flights(origins: list[str], destinations: list[str], departure: date,
                   return_date: date | None = None, currency: str | None = None,
                   cabin: Literal["economy", "premium", "business", "first"] = "economy",
                   adults: int = 1, max_stops: int | None = None, flex_days: int = 0,
                   nearby_km: int = 0, limit: int = 15) -> dict:
    """Search single ticket itineraries on Google Flights and Kiwi.com. Airports are IATA codes; metro codes
    like NYC, LON, PAR, BAY (SFO/OAK/SJC) expand automatically. flex_days searches +/- days on Kiwi.
    nearby_km adds airports within that radius (SAN also adds TIJ via the Cross Border Xpress)."""
    from .models import SearchQuery
    from .search import search

    q = SearchQuery(origins=origins, destinations=destinations, departure=departure, return_date=return_date,
                    currency=_cur(currency), cabin=cabin, adults=adults, max_stops=max_stops,
                    departure_flex_days=flex_days, return_flex_days=flex_days if return_date else 0,
                    nearby_km=nearby_km)
    res = search(q).model_dump(mode="json")
    _save("search", q.model_dump(mode="json"), res)
    return {"trips": _compact(res["trips"], limit), "errors": res["errors"], "google_flights_url": res["google_url"],
            "total_found": len(res["trips"])}


@mcp.tool()
def plan_routes(origins: list[str], destinations: list[str], depart_start: date, depart_end: date | None = None,
                return_start: date | None = None, return_end: date | None = None, currency: str | None = None,
                hubs: list[str] | None = None, max_stopover_days: int = 3, min_connection_hours: float = 3.0,
                max_trip_days: int | None = None, max_hubs: int = 8, nested_roundtrips: bool = True,
                limit: int = 15) -> dict:
    """Find cheaper routes than the normal search by combining separately booked tickets through hubs:
    same day self transfers, stopovers of up to max_stopover_days at a hub, and for round trips nested
    round trips (e.g. OSL-JFK return + JFK-SAN return). Slow: runs many searches (20 to 80)."""
    from .planner import PlanRequest, plan

    req = PlanRequest(origins=origins, destinations=destinations, depart_start=depart_start, depart_end=depart_end,
                      return_start=return_start, return_end=return_end, currency=_cur(currency), hubs=hubs or [],
                      max_stopover_days=max_stopover_days, min_connection_hours=min_connection_hours,
                      max_trip_days=max_trip_days, max_hubs=max_hubs, include_nested_roundtrips=nested_roundtrips)
    res = plan(req).model_dump(mode="json")
    _save("plan", req.model_dump(mode="json"), res)
    return {"trips": _compact(res["trips"], limit),
            "cheapest_single_ticket": res["direct"]["total_price"] if res.get("direct") else None,
            "hubs_tried": res["hubs_tried"], "searches": res["requests"], "errors": res["errors"]}


@mcp.tool()
def build_trip(start: str, stops: list[dict], earliest_departure: date, latest_departure: date | None = None,
               end: str | None = None, keep_order: bool = False, max_trip_days: int | None = None,
               currency: str | None = None) -> dict:
    """Build a multi city trip. stops: [{"place": "NYC", "min_nights": 2, "max_nights": 4}, ...].
    The order is optimized unless keep_order is true."""
    from .planner import TripRequest, TripStop, build_trip as run

    req = TripRequest(start=start, end=end, stops=[TripStop(**s) for s in stops], earliest_departure=earliest_departure,
                      latest_departure=latest_departure, keep_order=keep_order, max_trip_days=max_trip_days,
                      currency=_cur(currency))
    res = run(req).model_dump(mode="json")
    _save("trip", req.model_dump(mode="json"), res)
    return {"trips": _compact(res["trips"], 8), "errors": res["errors"]}


@mcp.tool()
def explore_destinations(origin: str, earliest: date, latest: date, nights_min: int | None = None,
                         nights_max: int | None = None, regions: list[str] | None = None,
                         currency: str | None = None, limit: int = 40) -> dict:
    """Cheapest destinations from an origin in a date window (Kiwi + Ryanair). regions can be continents or
    countries like "Europe", "Mexico". Give nights_min/max for round trips."""
    from .explore import explore

    nights = (nights_min or 1, nights_max or nights_min or 7) if (nights_min or nights_max) else None
    dests, errors = explore(origin, earliest, latest, _cur(currency), nights, regions=regions)
    payload = {"destinations": [d.model_dump(mode="json") for d in dests], "errors": errors}
    _save("explore", {"origin": origin, "from": str(earliest), "to": str(latest)}, payload)
    return {"destinations": payload["destinations"][:limit], "errors": errors, "total_found": len(dests)}


@mcp.tool()
def price_calendar(origin: str, destination: str, earliest: date, latest: date, trip_days: int | None = None,
                   currency: str | None = None) -> list[dict]:
    """Cheapest Google Flights price per departure date (one request per date, max 60 days)."""
    from .sources import google

    return [d.model_dump(mode="json") for d in google.dates(origin, destination, earliest, latest, _cur(currency), trip_days)]


@mcp.tool()
def find_airports(query: str) -> list[dict]:
    """Look up airport codes by city, name or code."""
    hits = airports.find(query)
    return [a.model_dump() for a in hits[:15]]


@mcp.tool()
def multicity_trip(start: str, legs: list[dict], currency: str | None = None, cabin: str = "economy",
                   adults: int = 1, watch: bool = False) -> dict:
    """Multi city trip in a fixed order. legs: [{"to": "JFK", "date": "2026-11-03", "flex_days": 2},
    {"to": "CDG", "date": "2026-11-15", "arrive_by": true}, ...]. Each flight is priced in its own date window
    (± flex_days, or any day from the previous flight up to "date" when arrive_by). watch=true also adds it to the
    user's watchlist."""
    from .multicity import Leg, MultiRequest, plan_multicity

    parsed, prev, prev_date = [], [start.upper()], None
    for lg in legs:
        d = date.fromisoformat(lg["date"])
        by = bool(lg.get("arrive_by"))
        n = int(lg.get("flex_days") or 0)
        parsed.append(Leg(origins=prev, destinations=[lg["to"].upper()], date=d,
                          before=((d - prev_date).days if prev_date else 14) if by else n,
                          after=0 if by else n, arrive_by=d if by else None))
        prev, prev_date = [lg["to"].upper()], d
    req = MultiRequest(legs=parsed, currency=_cur(currency), cabin=cabin, adults=adults)
    res = plan_multicity(req).model_dump(mode="json")
    _save("multicity", req.model_dump(mode="json"), res)
    out = {"trips": _compact(res["trips"], 8), "errors": res["errors"]}
    if watch:
        route = " → ".join([start.upper()] + [lg["to"].upper() for lg in legs])
        out["watch"] = Client().add_watch(name=route, origins=[start.upper()], destinations=parsed[-1].destinations,
                                          trip_type="multicity", depart_start=parsed[0].date.isoformat(),
                                          depart_end=parsed[-1].date.isoformat(),
                                          legs=[lg.model_dump(mode="json") for lg in parsed], currency=req.currency)
    return out


@mcp.tool()
def airline_links(origin: str | None = None, destination: str | None = None, depart: date | None = None,
                  return_date: date | None = None, region: str | None = None, query: str = "") -> list[dict]:
    """Airline directory: airlines (by region, name or tag) with links into each airline's own search, pre-filled
    with the route when origin, destination and depart are given. Regions: global, nordics, europe, us_domestic,
    north_america, mexico, central_america_caribbean, south_america, middle_east, africa, asia, oceania."""
    from . import airlines as directory

    rows = []
    for a in directory.find(query, region)[:60]:
        url, pre = directory.link(a, origin, destination, depart, return_date)
        rows.append({"iata": a["iata"], "name": a["name"], "category": a["category"], "tags": a.get("tags", []),
                     "url": url, "prefilled": pre})
    return rows


@mcp.tool()
def check_watch(watch_id: str) -> dict:
    """Price a watch right now (runs on the FlightScout server) and return the updated watch."""
    c = Client()
    c._req("POST", f"/watches/{watch_id}/check")
    w = c.watch(watch_id)
    return {k: v for k, v in w.items() if k not in ("best_trip", "user_id")}


@mcp.tool()
def list_watches() -> list[dict]:
    """The user's watchlist (tracked routes) with best price found so far."""
    drop = {"best_trip", "user_id", "sparkline"}
    return [{k: v for k, v in w.items() if k not in drop} for w in Client().watches()]


@mcp.tool()
def add_watch(origins: list[str], destinations: list[str], depart_start: date, depart_end: date | None = None,
              nights_min: int | None = None, nights_max: int | None = None, name: str | None = None,
              currency: str | None = None, alert_below: float | None = None, include_split: bool = True) -> dict:
    """Track a route daily. Give nights_min/max for round trips, omit for one way."""
    rt = bool(nights_min or nights_max)
    return Client().add_watch(
        name=name or f"{','.join(origins)} to {','.join(destinations)}", origins=origins, destinations=destinations,
        trip_type="roundtrip" if rt else "oneway", depart_start=depart_start.isoformat(),
        depart_end=depart_end.isoformat() if depart_end else None, nights_min=nights_min,
        nights_max=nights_max or nights_min, currency=_cur(currency), include_split=include_split,
        alert_below=alert_below, alert_drop_pct=10,
    )


@mcp.tool()
def watch_history(watch_id: str) -> list[dict]:
    """Price observations over time for a watch (for trends), newest last."""
    return [{k: v for k, v in o.items() if k != "trip"} for o in Client().history(watch_id)][-200:]


@mcp.tool()
def list_places() -> list[dict]:
    """The user's saved places: homes, frequent and interesting airports. Use these as defaults."""
    return Client().places()


def main() -> None:
    mcp.run()
