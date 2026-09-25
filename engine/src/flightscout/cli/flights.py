"""Flight search commands: search, plan, multicity, trip, dates."""

from __future__ import annotations

from datetime import timedelta
from enum import Enum
from typing import Optional

import typer
from rich.table import Table

from .common import (CurOpt, Fmt, FmtOpt, JsonOpt, SaveOpt, Sort, codes, con, cur, emit_csv, emit_json, filter_sort,
                     fmt_of, open_url, out, parse_date, save, show_trips)


class Preset(str, Enum):
    weekend = "weekend"
    week = "week"
    two_weeks = "2weeks"


def register(app: typer.Typer) -> None:
    app.command(rich_help_panel="Find flights")(search)
    app.command(rich_help_panel="Find flights")(plan)
    app.command(rich_help_panel="Find flights")(multicity)
    app.command(rich_help_panel="Find flights")(trip)
    app.command(rich_help_panel="Find flights")(dates)


def search(
    origin: str = typer.Argument(..., help="From: airport codes or metro, comma separated (SAN, OSL,TRF, NYC, BAY)."),
    destination: str = typer.Argument(..., help="To: airport codes or metro."),
    depart: str = typer.Argument(..., help="Departure: YYYY-MM-DD, today, tomorrow, +N or a weekday (fri)."),
    ret: Optional[str] = typer.Option(None, "--return", "-r", help="Return date (omit for one way)."),
    preset: Optional[Preset] = typer.Option(None, "--preset", "-p", help="weekend (next Fri to Sun), week or 2weeks."),
    flex: int = typer.Option(0, "--flex", help="± days on both dates."),
    depart_flex: Optional[int] = typer.Option(None, "--depart-flex", help="± days on the departure only."),
    return_flex: Optional[int] = typer.Option(None, "--return-flex", help="± days on the return only."),
    cabin: str = typer.Option("economy", help="economy, premium, business or first."),
    adults: int = typer.Option(1, help="Passengers (adults)."),
    max_stops: Optional[int] = typer.Option(None, "--max-stops", help="0 for nonstop only."),
    nearby: int = typer.Option(0, "--nearby", help="Also search airports within this many km (SAN adds TIJ)."),
    smart: bool = typer.Option(False, "--smart", help="Also look for cheaper separate ticket combinations (slower)."),
    sources: str = typer.Option("default", help="default, or a list: google,kiwiweb,kiwi,volaris,wideroe,skyairline,"
                                "norse,volotea,condor,flair,serpapi. With Chrome installed, any direct airline "
                                "source also brings in transavia, norwegian, southwest, vivaaerobus and allegiant "
                                "(read in a real browser, FLIGHTSCOUT_BROWSER=0 turns that off)."),
    max_price: Optional[float] = typer.Option(None, "--max-price", help="Hide results above this price."),
    sort: Sort = typer.Option(Sort.price, help="price, duration, departure or best (price + time)."),
    time_of_day: Optional[str] = typer.Option(None, "--time", help="morning, afternoon or evening departure."),
    airline: Optional[str] = typer.Option(None, "--airline", help="Only results with this airline (IATA, e.g. SK)."),
    no_self_transfer: bool = typer.Option(False, "--no-self-transfer", help="Hide self transfer itineraries."),
    sellers: int = typer.Option(0, "--sellers", help="Seller and fare breakdown for the top N Google results (browser)."),
    open_n: Optional[int] = typer.Option(None, "--open", help="Open the booking page of result N in your browser."),
    airline_links: bool = typer.Option(False, "--airline-links", help="Also print links to each airline's own site, pre-filled."),
    watch: bool = typer.Option(False, "--watch", help="Also add this search to your watchlist (same as the website button)."),
    limit: int = typer.Option(15, help="Rows to show."),
    currency: Optional[str] = CurOpt,
    fmt: Fmt = FmtOpt,
    as_json: bool = JsonOpt,
    keep: bool = SaveOpt,
):
    """Search flights across Google Flights (including the long, cheap connections from its Cheapest tab),
    Kiwi.com and airlines directly.

    Examples:
      flightscout search SAN OSL 2026-12-18 -r 2027-01-04
      flightscout search OSL CPH fri --preset weekend --max-price 1500 -c NOK
      flightscout search LAX DPS +60 -r +71 --depart-flex 3 --smart --sort best
    """
    from ..models import SearchQuery
    from ..search import search as run

    d = parse_date(depart)
    r = parse_date(ret) if ret else None
    df, rf = flex, flex
    if preset == Preset.weekend:
        d = d + timedelta(days=(4 - d.weekday()) % 7)  # next Friday
        r, df, rf = d + timedelta(days=2), max(flex, 1), max(flex, 1)
    elif preset in (Preset.week, Preset.two_weeks):
        r = d + timedelta(days=7 if preset == Preset.week else 14)
    df = depart_flex if depart_flex is not None else df
    rf = return_flex if return_flex is not None else rf
    src = {} if sources.strip().lower() == "default" else {
        "sources": [s.strip().lower() for s in sources.split(",") if s.strip()]}
    q = SearchQuery(origins=codes(origin), destinations=codes(destination), departure=d, return_date=r, cabin=cabin,
                    adults=adults, max_stops=max_stops, currency=cur(currency), departure_flex_days=df,
                    return_flex_days=rf if r else 0, nearby_km=nearby, **src)
    with con.status("searching Google Flights, Kiwi.com and airlines..."):
        res = run(q)
    trips = list(res.trips)
    if smart:
        from ..planner import PlanRequest, plan as run_plan

        with con.status("looking for cheaper combinations (about a minute)..."):
            pr = run_plan(PlanRequest(origins=q.origins, destinations=q.destinations, depart_start=d - timedelta(days=df),
                                      depart_end=d + timedelta(days=df), return_start=r - timedelta(days=rf) if r else None,
                                      return_end=r + timedelta(days=rf) if r else None, currency=q.currency, cabin=cabin,
                                      adults=adults, max_hubs=6, max_stopover_days=2))
        seen = {t.id for t in trips}
        trips += [t for t in pr.trips if t.id not in seen and t.kind != "single"]
    if sellers:
        from ..sellers_live import enrich

        with con.status("reading seller prices..."):
            enrich(trips, sellers)
    save("search", q.model_dump(mode="json"), res, keep)
    trips = filter_sort(trips, sort, max_price, max_stops, time_of_day, no_self_transfer, airline)
    f = fmt_of(fmt, as_json)
    show_trips(trips, f, limit, f"{','.join(q.origins)} to {','.join(q.destinations)}",
               payload={**res.model_dump(mode="json"), "trips": [t.model_dump(mode="json") for t in trips]})
    if f != Fmt.table:
        return
    singles = [t for t in trips if t.kind == "single"]
    combos = [t for t in trips if t.kind != "single"]
    if singles and combos and min(c.total_price for c in combos) < min(s.total_price for s in singles):
        best = min(combos, key=lambda t: t.total_price)
        out.print(f"[green]Cheaper combination: {best.total_price:,.0f} {best.currency} via {'-'.join(best.route)} "
                  f"({len(best.tickets)} separate tickets), saves "
                  f"{min(s.total_price for s in singles) - best.total_price:,.0f}[/green]")
    if sellers:
        for i, tr in enumerate(trips[:limit], 1):
            for tk in tr.tickets:
                if tk.offers:
                    out.print(f"[bold]#{i}[/bold] {'-'.join(tr.route)}  [dim]{tk.price_insight or ''}[/dim]")
                    for o in tk.offers:
                        tag = "[green]airline[/green]" if o.is_airline else "[yellow]agency[/yellow]"
                        out.print(f"   {o.seller} ({tag}): " + ", ".join(f"{x.name or 'fare'} {x.price:,.0f}" for x in o.fares))
    if airline_links:
        _print_airline_links(trips[:limit])
    if res.errors:
        con.print(f"[dim]some sources didn't respond: {', '.join(res.errors)}[/dim]")
    if res.google_url:
        out.print(f"Google Flights: {res.google_url}")
    if watch:
        _watch(name=f"{','.join(q.origins)} to {','.join(q.destinations)}", origins=q.origins, destinations=q.destinations,
               trip_type="roundtrip" if r else "oneway", depart_start=(d - timedelta(days=df)).isoformat(),
               depart_end=(d + timedelta(days=df)).isoformat(),
               nights_min=max(0, (r - d).days - df - rf) if r else None, nights_max=(r - d).days + df + rf if r else None,
               currency=q.currency, cabin=cabin, adults=adults, include_split=smart)
    if open_n:
        if 1 <= open_n <= len(trips):
            for tk in trips[open_n - 1].tickets:
                open_url(tk.booking_url)
        else:
            con.print(f"[yellow]no result #{open_n}[/yellow]")


def _watch(**body) -> None:
    from .common import client

    w = client().add_watch(**body)
    if w.get("existing"):
        out.print(f"[green]Already watching[/green] {w.get('name')} (id {w['id']}).")
    else:
        out.print(f"[green]Watching[/green] {w.get('name')} (id {w['id']}). Prices are checked twice a day.")


def _print_airline_links(trips) -> None:
    from .. import airlines as directory

    for i, t in enumerate(trips, 1):
        parts = []
        for tk in t.tickets:
            sl = tk.slices[0]
            back = tk.slices[1].departure.date() if len(tk.slices) > 1 else None
            for code in sorted({s.carrier for x in tk.slices for s in x.segments}):
                a = directory.get(code)
                if a:
                    url, pre = directory.link(a, sl.origin, sl.destination, sl.departure.date(), back)
                    parts.append(f"[link={url}]{a['name']}{'' if pre else ' (site)'}[/link]")
        if parts:
            out.print(f"#{i} check on the airline: " + ", ".join(dict.fromkeys(parts)))


def plan(
    origin: str = typer.Argument(..., help="From (airports or metro)."),
    destination: str = typer.Argument(..., help="To (airports or metro)."),
    depart: str = typer.Argument(..., help="Earliest departure date."),
    depart_end: Optional[str] = typer.Option(None, "--depart-end", help="Latest departure date."),
    ret: Optional[str] = typer.Option(None, "--return", "-r", help="Earliest return date (round trip)."),
    ret_end: Optional[str] = typer.Option(None, "--return-end", help="Latest return date."),
    hubs: str = typer.Option("", help="Extra hubs to always try, e.g. JFK,LHR."),
    max_hubs: int = typer.Option(8, "--max-hubs", help="How many hubs to try (more = slower)."),
    max_stopover_days: int = typer.Option(3, "--max-stopover-days", help="Longest stay at a hub between tickets."),
    min_connection: float = typer.Option(3.0, "--min-connection", help="Hours needed between separate tickets."),
    max_trip_days: Optional[int] = typer.Option(None, "--max-trip-days", help="Longest whole trip."),
    max_travel_hours: Optional[float] = typer.Option(None, "--max-travel-hours", help="Longest travel time per direction."),
    nested: bool = typer.Option(True, "--nested/--no-nested", help="Try nested round trips (A-hub return + hub-B return)."),
    value_of_time: float = typer.Option(15.0, "--value-of-time", help="Money per hour of travel, for ranking."),
    cabin: str = typer.Option("economy"),
    max_price: Optional[float] = typer.Option(None, "--max-price"),
    sort: Sort = typer.Option(Sort.best, help="best (default), price, duration or departure."),
    limit: int = typer.Option(20),
    currency: Optional[str] = CurOpt,
    fmt: Fmt = FmtOpt,
    as_json: bool = JsonOpt,
    keep: bool = SaveOpt,
):
    """Cheaper routes from separate tickets: split tickets, stopovers, nested round trips and positioning
    flights through hubs and gateways near you (e.g. San Diego via LAX).

    Examples:
      flightscout plan SAN DPS 2027-02-11 -r 2027-02-22
      flightscout plan OSL SAN +40 --hubs JFK,KEF --max-stopover-days 2
    """
    from ..planner import PlanRequest, plan as run

    req = PlanRequest(origins=codes(origin), destinations=codes(destination), depart_start=parse_date(depart),
                      depart_end=parse_date(depart_end) if depart_end else None,
                      return_start=parse_date(ret) if ret else None, return_end=parse_date(ret_end) if ret_end else None,
                      currency=cur(currency), cabin=cabin, hubs=codes(hubs), max_hubs=max_hubs,
                      max_stopover_days=max_stopover_days, min_connection_hours=min_connection,
                      max_trip_days=max_trip_days, max_travel_hours=max_travel_hours,
                      include_nested_roundtrips=nested, value_of_time_per_hour=value_of_time)
    with con.status("planning (this runs many searches, about a minute)..."):
        res = run(req)
    save("plan", req.model_dump(mode="json"), res, keep)
    trips = filter_sort(res.trips, sort, max_price)
    show_trips(trips, fmt_of(fmt, as_json), limit, f"Routes {origin} to {destination}",
               payload={**res.model_dump(mode="json"), "trips": [t.model_dump(mode="json") for t in trips]})
    if fmt_of(fmt, as_json) == Fmt.table:
        if res.direct:
            out.print(f"Cheapest single ticket: {res.direct.total_price:,.0f} {res.direct.currency}")
        con.print(f"[dim]hubs tried: {', '.join(res.hubs_tried)}. {res.requests} searches.[/dim]")


def multicity(
    start: str = typer.Argument(..., help="Where the trip starts (airport or metro)."),
    legs: list[str] = typer.Argument(..., help="Stops in order: PLACE@DATE, optionally ±N days (JFK@2026-11-03±2) or "
                                     "'by' for arrive by (CDG@by2026-11-15). Use ~N instead of ±N if your shell prefers."),
    currency: Optional[str] = CurOpt,
    cabin: str = typer.Option("economy"),
    adults: int = typer.Option(1),
    min_gap: float = typer.Option(4.0, "--min-gap", help="Hours needed between landing and the next flight."),
    watch: bool = typer.Option(False, "--watch", help="Also add this multi city trip to your watchlist."),
    limit: int = typer.Option(10),
    fmt: Fmt = FmtOpt,
    as_json: bool = JsonOpt,
    keep: bool = SaveOpt,
):
    """Multi city trip in a fixed order, each flight with its own date window.

    Examples:
      flightscout multicity SAN JFK@2026-11-03±2 OSL@2026-11-07±3 CDG@by2026-11-15 SAN@2026-11-20±1
    """
    from ..multicity import Leg, MultiRequest, plan_multicity

    parsed, prev, prev_date = [], codes(start), None
    for spec in legs:
        place, _, when = spec.partition("@")
        if not when:
            raise typer.BadParameter(f"'{spec}' needs a date: PLACE@YYYY-MM-DD")
        by = when.lower().startswith("by")
        when = when[2:] if by else when
        n = 0
        for sep in ("±", "~"):
            if sep in when:
                when, _, nn = when.partition(sep)
                n = int(nn)
        d = parse_date(when)
        before = (d - prev_date).days if (by and prev_date) else (14 if by else n)
        parsed.append(Leg(origins=prev, destinations=codes(place), date=d, before=max(0, before),
                          after=0 if by else n, arrive_by=d if by else None))
        prev, prev_date = codes(place), d
    req = MultiRequest(legs=parsed, currency=cur(currency), cabin=cabin, adults=adults, min_gap_hours=min_gap)
    with con.status("pricing every flight in its window..."):
        res = plan_multicity(req)
    save("multicity", req.model_dump(mode="json"), res, keep)
    route = " → ".join([start.upper()] + [lg.split("@")[0].upper() for lg in legs])
    show_trips(res.trips, fmt_of(fmt, as_json), limit, route, payload=res)
    for k, v in res.errors.items():
        con.print(f"[yellow]{k}: {v}[/yellow]")
    if watch:
        _watch(name=route, origins=codes(start), destinations=parsed[-1].destinations, trip_type="multicity",
               depart_start=parsed[0].date.isoformat(), depart_end=parsed[-1].date.isoformat(),
               legs=[{**lg.model_dump(mode="json")} for lg in parsed], currency=req.currency, cabin=cabin, adults=adults)


def trip(
    start: str = typer.Argument(..., help="Home airport the trip starts from."),
    stops: list[str] = typer.Option(..., "--stop", "-s", help="PLACE or PLACE:MIN-MAX nights, repeatable."),
    earliest: str = typer.Option(..., "--from", help="Earliest departure."),
    latest: Optional[str] = typer.Option(None, "--to", help="Latest first departure."),
    end: Optional[str] = typer.Option(None, "--end", help="Where the trip ends (default: start)."),
    keep_order: bool = typer.Option(False, "--keep-order", help="Visit stops in the given order."),
    max_trip_days: Optional[int] = typer.Option(None, "--max-trip-days"),
    currency: Optional[str] = CurOpt,
    fmt: Fmt = FmtOpt,
    as_json: bool = JsonOpt,
    keep: bool = SaveOpt,
):
    """Build a trip through several places, letting FlightScout choose the order and dates.

    Examples:
      flightscout trip OSL -s NYC:2-4 -s SAN:5-10 -s MEX:3-5 --from 2026-11-10 --to 2026-11-14
    """
    from ..planner import TripRequest, TripStop, build_trip

    parsed = []
    for s in stops:
        place, _, rng = s.partition(":")
        lo, _, hi = rng.partition("-")
        parsed.append(TripStop(place=place.upper(), min_nights=int(lo or 2), max_nights=int(hi or lo or 5)))
    req = TripRequest(start=start.upper(), end=end.upper() if end else None, stops=parsed,
                      earliest_departure=parse_date(earliest), latest_departure=parse_date(latest) if latest else None,
                      keep_order=keep_order, max_trip_days=max_trip_days, currency=cur(currency))
    with con.status("building trip..."):
        res = build_trip(req)
    save("trip", req.model_dump(mode="json"), res, keep)
    show_trips(res.trips, fmt_of(fmt, as_json), 10, "Trip options", payload=res)


def dates(
    origin: str = typer.Argument(..., help="From."),
    destination: str = typer.Argument(..., help="To."),
    earliest: str = typer.Option("+7", "--from", help="First departure date to price."),
    latest: str = typer.Option("+37", "--to", help="Last departure date (max 60 days after --from)."),
    trip_days: Optional[int] = typer.Option(None, "--trip-days", help="Round trips of this many nights."),
    currency: Optional[str] = CurOpt,
    fmt: Fmt = FmtOpt,
    as_json: bool = JsonOpt,
):
    """Cheapest price per departure date: Google Flights plus airline and Skyscanner calendars.

    Examples:
      flightscout dates OSL SAN --from 2026-11-01 --to 2026-11-30
      flightscout dates TIJ GDL --from +10 --to +40 -c MXN
    """
    from ..search import cheapest_per_day, direct_dates
    from ..sources import google

    o, d = origin.upper(), destination.upper()
    with con.status("pricing dates..."):
        res = google.dates(o, d, parse_date(earliest), parse_date(latest), cur(currency), trip_days)
        if not trip_days:  # airline calendars are one way only
            extra, errs = direct_dates(o, d, parse_date(earliest), parse_date(latest), cur(currency))
            for n, e in errs.items():
                con.print(f"[dim]{n} calendar failed: {e}[/dim]")
            res = cheapest_per_day(res + extra)
    f = fmt_of(fmt, as_json)
    if f == Fmt.json:
        return emit_json([r.model_dump(mode="json") for r in res])
    if f == Fmt.csv:
        return emit_csv([{"date": r.departure, "return": r.return_date, "price": r.price, "currency": r.currency,
                          "source": r.source} for r in res])
    lo = min((r.price for r in res), default=0)
    t = Table(title=f"{o} to {d} by date", header_style="bold")
    for c in ("Date", "Return", "Price", "Source", ""):
        t.add_column(c)
    for r in sorted(res, key=lambda r: r.departure):
        bar = "█" * max(1, int(20 * lo / r.price)) if r.price else ""
        t.add_row(r.departure.strftime("%a %d %b"), str(r.return_date or ""), f"{r.price:,.0f} {r.currency}", r.source,
                  f"[green]{bar}[/green]" if r.price == lo else bar)
    out.print(t)
