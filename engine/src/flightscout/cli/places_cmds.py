"""Discovery: explore anywhere, airports and the airline directory."""

from __future__ import annotations

from datetime import timedelta
from typing import Optional

import typer
from rich.table import Table

from .. import airlines as airline_dir
from .. import airports
from .common import (CurOpt, Fmt, FmtOpt, JsonOpt, SaveOpt, con, cur, emit_csv, emit_json, fmt_of, nights_range,
                     open_url, out, parse_date, save)


def register(app: typer.Typer) -> None:
    app.command(rich_help_panel="Discover")(explore)
    app.command("airports", rich_help_panel="Discover")(airports_cmd)
    app.command("airlines", rich_help_panel="Discover")(airlines_cmd)


def explore(
    origin: str = typer.Argument(..., help="Where you start (airport or metro, e.g. SAN or OSLX)."),
    earliest: str = typer.Option("+7", "--from", help="Earliest departure."),
    latest: str = typer.Option("+60", "--to", help="Latest departure."),
    nights: Optional[str] = typer.Option(None, help="Round trips of MIN-MAX nights (e.g. 2-3 weekend, 5-9 a week)."),
    weekend: bool = typer.Option(False, "--weekend", help="Shortcut: 2-3 night trips."),
    one_way: bool = typer.Option(False, "--one-way", help="One way flights instead of round trips."),
    max_price: Optional[float] = typer.Option(None, "--max-price", help="Only places under this price."),
    country: Optional[str] = typer.Option(None, help="Only this country (ISO code, e.g. MX, IT)."),
    deep: bool = typer.Option(False, "--deep", help="Also run the slower region by region lookups."),
    regions: str = typer.Option("", help="Custom regions or countries for --deep, e.g. 'Europe,Mexico'."),
    sort: str = typer.Option("price", help="price or date."),
    open_n: Optional[int] = typer.Option(None, "--open", help="Open the booking page of row N."),
    limit: int = typer.Option(40),
    currency: Optional[str] = CurOpt,
    fmt: Fmt = FmtOpt,
    as_json: bool = JsonOpt,
    keep: bool = SaveOpt,
):
    """Cheapest places to go from ORIGIN (Google Explore, Kiwi, KAYAK, Ryanair).

    Examples:
      flightscout explore SAN --weekend --max-price 200
      flightscout explore OSL --from 2026-11-01 --to 2026-11-30 --nights 5-9 -c NOK
      flightscout explore OSL --one-way --country ES
    """
    from ..explore import BATCHES, explore as run

    n = None if one_way else ((2, 3) if weekend else (nights_range(nights) or (3, 10)))
    c = cur(currency)
    lo, hi = parse_date(earliest), parse_date(latest)
    with con.status("exploring..."):
        dests, errors = run(origin.upper(), lo, hi, c, n, sources=["google", "kiwiweb", "kayak", "ryanair"],
                            regions=["anywhere"])
        if deep:
            wanted = [r.strip() for r in regions.split(",") if r.strip()] or [x for b in BATCHES for x in b]
            more, e2 = run(origin.upper(), lo, hi, c, n, sources=["kiwi"], regions=wanted)
            errors.update(e2)
            best = {d.destination: d for d in dests}
            for d in more:
                if d.destination not in best or d.price < best[d.destination].price:
                    best[d.destination] = d
            dests = list(best.values())
    dests = [d for d in dests if (max_price is None or d.price <= max_price) and (not country or d.country == country.upper())]
    dests.sort(key=(lambda d: d.price) if sort == "price" else (lambda d: str(d.departure)))
    payload = {"destinations": [d.model_dump(mode="json") for d in dests], "errors": errors}
    save("explore", {"origin": origin.upper(), "from": str(lo), "to": str(hi), "nights": n, "currency": c}, payload, keep)
    f = fmt_of(fmt, as_json)
    if f == Fmt.json:
        return emit_json(payload)
    if f == Fmt.csv:
        return emit_csv([{k: v for k, v in d.model_dump(mode="json").items() if k not in ("lat", "lon")} for d in dests[:limit]])
    t = Table(title=f"Cheapest from {origin.upper()} ({len(dests)} places)", header_style="bold")
    for col in ("#", "Price", "To", "City", "Country", "Depart", "Return", "Source", "Book"):
        t.add_column(col)
    for i, d in enumerate(dests[:limit], 1):
        t.add_row(str(i), f"{d.price:,.0f} {d.currency}", d.destination, d.city or "", d.country or "",
                  str(d.departure or ""), str(d.return_date or ""), d.source,
                  f"[link={d.booking_url}]open[/link]" if d.booking_url else "")
    out.print(t)
    out.print("[dim]Search one: flightscout search " + origin.upper() + " <CODE> <date>[/dim]")
    if open_n and 1 <= open_n <= len(dests) and dests[open_n - 1].booking_url:
        open_url(dests[open_n - 1].booking_url)


def airports_cmd(query: str = typer.Argument(..., help="Code, city or name (accents optional: cancun)."),
                 nearby: Optional[int] = typer.Option(None, "--nearby", help="Instead list airports within N km of QUERY."),
                 fmt: Fmt = FmtOpt, as_json: bool = JsonOpt):
    """Look up airports, or list the ones near an airport."""
    if nearby:
        rows = [airports.get(c) for c in airports.nearby(query, nearby)]
    else:
        rows = airports.find(query)
    rows = [r for r in rows if r]
    f = fmt_of(fmt, as_json)
    if f == Fmt.json:
        return emit_json([a.model_dump() for a in rows])
    if f == Fmt.csv:
        return emit_csv([a.model_dump() for a in rows])
    for a in rows:
        dist = f"  {airports.haversine_km(query.upper(), a.iata):,.0f} km" if nearby else ""
        out.print(f"{a.iata}  {a.name}, {a.city} ({a.country}){dist}")


def airlines_cmd(
    query: str = typer.Argument("", help="Name, code or tag (e.g. 'free carry-on'). Empty lists all."),
    region: Optional[str] = typer.Option(None, help="global, nordics, europe, us_domestic, north_america, mexico, "
                                          "central_america_caribbean, south_america, middle_east, africa, asia, oceania."),
    category: Optional[str] = typer.Option(None, help="budget, full_service, low_cost, ultra_low_cost, regional..."),
    alliance: Optional[str] = typer.Option(None, help="star, oneworld, skyteam or none."),
    route: Optional[str] = typer.Option(None, help="FROM-TO to get pre-filled search links, e.g. OSL-CPH."),
    depart: Optional[str] = typer.Option(None, "--depart", "-d", help="Departure date for --route."),
    ret: Optional[str] = typer.Option(None, "--return", "-r", help="Return date for --route."),
    open_code: Optional[str] = typer.Option(None, "--open", help="Open this airline's search (IATA code) in the browser."),
    fmt: Fmt = FmtOpt,
    as_json: bool = JsonOpt,
):
    """Airline directory: go straight to an airline's own search, pre-filled with your route.

    Examples:
      flightscout airlines --region nordics
      flightscout airlines --route OSL-CPH -d 2026-11-20 -r 2026-11-27 --open SK
      flightscout airlines "free carry-on" --category budget
    """
    o = dst = None
    if route:
        o, _, dst = route.upper().partition("-")
    dd = parse_date(depart) if depart else (parse_date("+14") if route else None)
    rr = parse_date(ret) if ret else None
    items = airline_dir.find(query, region, category, alliance)
    rows = []
    for a in items:
        url, pre = airline_dir.link(a, o, dst, dd, rr)
        rows.append({"iata": a["iata"], "name": a["name"], "category": airline_dir.CATEGORIES.get(a["category"], a["category"]),
                     "alliance": a.get("alliance") or "", "hubs": ",".join(a.get("hubs", [])[:3]),
                     "tags": ", ".join(a.get("tags", [])[:4]), "url": url, "prefilled": pre})
    if open_code:
        hit = next((r for r in rows if r["iata"] == open_code.upper()), None)
        if not hit:
            raise typer.BadParameter(f"{open_code} not in this list")
        return open_url(hit["url"])
    f = fmt_of(fmt, as_json)
    if f == Fmt.json:
        return emit_json(rows)
    if f == Fmt.csv:
        return emit_csv(rows)
    t = Table(title=f"{len(rows)} airlines", header_style="bold")
    for col in ("Code", "Airline", "Type", "Alliance", "Hubs", "Tags", "Search"):
        t.add_column(col, overflow="fold")
    for r in rows:
        t.add_row(r["iata"], r["name"], r["category"], r["alliance"], r["hubs"], r["tags"],
                  f"[link={r['url']}]{'route' if r['prefilled'] else 'site'}[/link]")
    out.print(t)
