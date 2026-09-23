"""`flightscout` command line. Human friendly tables by default, `--json` for
AI agents. When logged in to the web app, results are also saved there so they
show up in the browser (disable with --no-save)."""

from __future__ import annotations

import json
import logging
import sys
import webbrowser
from datetime import date, timedelta
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from . import airports, config
from .client import Client, NotLoggedIn

app = typer.Typer(no_args_is_help=True, add_completion=False,
                  help="FlightScout: find flights, smarter routes and cheap destinations; track prices.")
watch_app = typer.Typer(no_args_is_help=True, help="Watchlist: tracked routes with price history.")
places_app = typer.Typer(no_args_is_help=True, help="Saved places: homes, frequent and interesting airports.")
app.add_typer(watch_app, name="watch")
app.add_typer(places_app, name="places")

con = Console(stderr=True)
out = Console()

JsonOpt = typer.Option(False, "--json", help="Machine readable JSON on stdout (for agents).")
SaveOpt = typer.Option(True, "--save/--no-save", help="Save the result to your web account if logged in.")


def _cur(c: Optional[str]) -> str:
    return (c or config.load().get("currency") or "USD").upper()


def _date(s: str) -> date:
    s = s.strip().lower()
    if s == "today":
        return date.today()
    if s == "tomorrow":
        return date.today() + timedelta(days=1)
    if s.startswith("+") and s[1:].isdigit():
        return date.today() + timedelta(days=int(s[1:]))
    return date.fromisoformat(s)


def _codes(s: str) -> list[str]:
    return [c.strip().upper() for c in s.split(",") if c.strip()]


def _emit_json(obj) -> None:
    if hasattr(obj, "model_dump"):
        obj = obj.model_dump(mode="json")
    sys.stdout.write(json.dumps(obj, indent=2, default=str) + "\n")


def _save(kind: str, query: dict, payload, save: bool) -> None:
    if not save:
        return
    c = Client()
    if not c.ready or not c.token:
        return
    try:
        c.save_result(kind, query, payload.model_dump(mode="json") if hasattr(payload, "model_dump") else payload)
        con.print(f"[dim]saved to {c.base}[/dim]")
    except Exception as e:
        con.print(f"[yellow]could not save to web app: {e}[/yellow]")


def _fmt_min(m: int) -> str:
    return f"{m // 60}h{m % 60:02d}"


def _trips_table(trips, limit: int, title: str) -> Table:
    t = Table(title=title, show_lines=False, header_style="bold")
    for col in ("#", "Price", "Kind", "Route", "Depart", "Arrive", "Travel", "Airlines", "Book"):
        t.add_column(col, overflow="fold")
    for i, tr in enumerate(trips[:limit], 1):
        carriers = sorted({c for tk in tr.tickets for sl in tk.slices for c in sl.carriers})
        kind = tr.kind + (f" ({len(tr.tickets)} tickets)" if len(tr.tickets) > 1 else "")
        if tr.stopovers:
            kind += " " + ", ".join(f"{s.airport} {s.hours / 24:.1f}d" if s.hours >= 24 else f"{s.airport} {s.hours:.0f}h" for s in tr.stopovers)
        if any(tk.self_transfer for tk in tr.tickets):
            kind += " [yellow]self transfer[/yellow]"
        links = "\n".join(f"[link={tk.booking_url}]{tk.seller or tk.source}[/link]" for tk in tr.tickets)
        price = f"{tr.total_price:,.0f} {tr.currency}"
        if tr.savings_vs_direct and tr.savings_vs_direct > 0:
            price += f"\n[green]-{tr.savings_vs_direct:,.0f}[/green]"
        t.add_row(str(i), price, kind, "-".join(tr.route), tr.departure.strftime("%a %d %b %H:%M"),
                  tr.arrival.strftime("%a %d %b %H:%M"), _fmt_min(tr.travel_min), ",".join(carriers), links)
    return t


@app.command()
def search(
    origin: str = typer.Argument(..., help="Origin airport(s) or metro, comma separated (OSL, NYC, SAN,LAX)"),
    destination: str = typer.Argument(..., help="Destination airport(s) or metro"),
    depart: str = typer.Argument(..., help="Departure date YYYY-MM-DD, today, tomorrow or +N"),
    ret: Optional[str] = typer.Option(None, "--return", "-r", help="Return date for a round trip"),
    flex: int = typer.Option(0, "--flex", help="Kiwi: +/- days around the dates"),
    cabin: str = typer.Option("economy", help="economy, premium, business, first"),
    adults: int = typer.Option(1),
    max_stops: Optional[int] = typer.Option(None, "--max-stops"),
    currency: Optional[str] = typer.Option(None, "--currency", "-c"),
    sources: str = typer.Option("default", help="default (google, kiwi and the airline direct sources) or a list: "
                                "google,kiwi,serpapi,volaris,wideroe,skyairline,norse,volotea,condor,flair"),
    nearby: int = typer.Option(0, "--nearby", help="Also search airports within this many km"),
    sellers: int = typer.Option(0, "--sellers", help="Fetch the seller breakdown for the top N Google results (needs a browser)"),
    limit: int = typer.Option(15),
    as_json: bool = JsonOpt,
    save: bool = SaveOpt,
):
    """Search one ticket itineraries across all sources."""
    from .models import SearchQuery
    from .search import search as run

    src = {} if sources.strip().lower() == "default" else {
        "sources": [s.strip().lower() for s in sources.split(",") if s.strip()]}
    q = SearchQuery(origins=_codes(origin), destinations=_codes(destination), departure=_date(depart),
                    return_date=_date(ret) if ret else None, cabin=cabin, adults=adults, max_stops=max_stops,
                    currency=_cur(currency), departure_flex_days=flex, return_flex_days=flex if ret else 0,
                    nearby_km=nearby, **src)
    with con.status("searching..."):
        res = run(q)
    if sellers:
        from .sellers_live import enrich

        with con.status("reading seller prices..."):
            enrich(res.trips, sellers)
    _save("search", q.model_dump(mode="json"), res, save)
    if as_json:
        return _emit_json(res)
    out.print(_trips_table(res.trips, limit, f"{','.join(q.origins)} to {','.join(q.destinations)}"))
    if sellers:
        for i, tr in enumerate(res.trips, 1):
            for tk in tr.tickets:
                if not tk.offers:
                    continue
                out.print(f"[bold]#{i}[/bold] {'-'.join(tr.route)}  [dim]{tk.price_insight or ''}[/dim]")
                for o in tk.offers:
                    tag = "[green]airline[/green]" if o.is_airline else "[yellow]agency[/yellow]"
                    fares = ", ".join(f"{f.name or 'fare'} {f.price:,.0f}" for f in o.fares)
                    out.print(f"   {o.seller} ({tag}): {fares}")
                for w in tk.warnings:
                    out.print(f"   [yellow]! {w}[/yellow]")
    if res.errors:
        con.print(f"[yellow]source errors: {res.errors}[/yellow]")
    if res.google_url:
        out.print(f"Google Flights: {res.google_url}")


@app.command()
def plan(
    origin: str = typer.Argument(...),
    destination: str = typer.Argument(...),
    depart: str = typer.Argument(..., help="Earliest departure date"),
    depart_end: Optional[str] = typer.Option(None, "--depart-end", help="Latest departure date"),
    ret: Optional[str] = typer.Option(None, "--return", "-r", help="Earliest return date"),
    ret_end: Optional[str] = typer.Option(None, "--return-end"),
    hubs: str = typer.Option("", help="Extra hubs to always try, e.g. JFK,LHR"),
    max_hubs: int = typer.Option(8, "--max-hubs"),
    max_stopover_days: int = typer.Option(3, "--max-stopover-days"),
    min_connection: float = typer.Option(3.0, "--min-connection", help="Hours between separate tickets"),
    max_trip_days: Optional[int] = typer.Option(None, "--max-trip-days"),
    max_travel_hours: Optional[float] = typer.Option(None, "--max-travel-hours"),
    nested: bool = typer.Option(True, "--nested/--no-nested", help="Try nested round trips via hubs"),
    value_of_time: float = typer.Option(15.0, "--value-of-time", help="Per hour, used for ranking"),
    currency: Optional[str] = typer.Option(None, "--currency", "-c"),
    cabin: str = typer.Option("economy"),
    limit: int = typer.Option(20),
    as_json: bool = JsonOpt,
    save: bool = SaveOpt,
):
    """Find smarter routes: split tickets, stopovers and nested round trips via hubs."""
    from .planner import PlanRequest, plan as run

    req = PlanRequest(origins=_codes(origin), destinations=_codes(destination), depart_start=_date(depart),
                      depart_end=_date(depart_end) if depart_end else None,
                      return_start=_date(ret) if ret else None, return_end=_date(ret_end) if ret_end else None,
                      currency=_cur(currency), cabin=cabin, hubs=_codes(hubs), max_hubs=max_hubs,
                      max_stopover_days=max_stopover_days, min_connection_hours=min_connection,
                      max_trip_days=max_trip_days, max_travel_hours=max_travel_hours,
                      include_nested_roundtrips=nested, value_of_time_per_hour=value_of_time)
    with con.status("planning (this runs many searches)..."):
        res = run(req)
    _save("plan", req.model_dump(mode="json"), res, save)
    if as_json:
        return _emit_json(res)
    out.print(_trips_table(res.trips, limit, f"Routes {origin} to {destination} (ranked by price + time)"))
    if res.direct:
        out.print(f"Cheapest single ticket: {res.direct.total_price:,.0f} {res.direct.currency}")
    con.print(f"[dim]hubs tried: {', '.join(res.hubs_tried)}. {res.requests} searches.[/dim]")


@app.command()
def trip(
    start: str = typer.Argument(..., help="Home airport the trip starts from"),
    stops: list[str] = typer.Option(..., "--stop", "-s", help="PLACE or PLACE:MIN-MAX nights, repeatable"),
    earliest: str = typer.Option(..., "--from", help="Earliest departure"),
    latest: Optional[str] = typer.Option(None, "--to", help="Latest first departure"),
    end: Optional[str] = typer.Option(None, "--end", help="Where the trip ends (default: start)"),
    keep_order: bool = typer.Option(False, "--keep-order", help="Visit stops in the given order"),
    max_trip_days: Optional[int] = typer.Option(None, "--max-trip-days"),
    currency: Optional[str] = typer.Option(None, "--currency", "-c"),
    as_json: bool = JsonOpt,
    save: bool = SaveOpt,
):
    """Build a multi city trip from scratch (e.g. OSL -s NYC:2-4 -s SAN:5-10 -s MEX:3-5)."""
    from .planner import TripRequest, TripStop, build_trip

    parsed = []
    for s in stops:
        place, _, rng = s.partition(":")
        lo, _, hi = rng.partition("-")
        parsed.append(TripStop(place=place.upper(), min_nights=int(lo or 2), max_nights=int(hi or lo or 5)))
    req = TripRequest(start=start.upper(), end=end.upper() if end else None, stops=parsed,
                      earliest_departure=_date(earliest), latest_departure=_date(latest) if latest else None,
                      keep_order=keep_order, max_trip_days=max_trip_days, currency=_cur(currency))
    with con.status("building trip..."):
        res = build_trip(req)
    _save("trip", req.model_dump(mode="json"), res, save)
    if as_json:
        return _emit_json(res)
    out.print(_trips_table(res.trips, 10, "Trip options"))


@app.command()
def explore(
    origin: str = typer.Argument(..., help="Where you start"),
    earliest: str = typer.Option("+7", "--from"),
    latest: str = typer.Option("+60", "--to"),
    nights: Optional[str] = typer.Option(None, help="Round trips of MIN-MAX nights, e.g. 3-7"),
    regions: str = typer.Option("", help="Limit to regions/countries, e.g. 'Europe,Mexico'"),
    currency: Optional[str] = typer.Option(None, "--currency", "-c"),
    limit: int = typer.Option(40),
    as_json: bool = JsonOpt,
    save: bool = SaveOpt,
):
    """Cheapest places to go from ORIGIN in a date window."""
    from .explore import explore as run

    n = None
    if nights:
        lo, _, hi = nights.partition("-")
        n = (int(lo), int(hi or lo))
    cur = _cur(currency)
    with con.status("exploring..."):
        dests, errors = run(origin.upper(), _date(earliest), _date(latest), cur, n,
                            regions=[r.strip() for r in regions.split(",") if r.strip()] or None)
    payload = {"destinations": [d.model_dump(mode="json") for d in dests], "errors": errors}
    _save("explore", {"origin": origin, "from": earliest, "to": latest, "nights": nights, "currency": cur}, payload, save)
    if as_json:
        return _emit_json(payload)
    t = Table(title=f"Cheapest from {origin.upper()}", header_style="bold")
    for c in ("Price", "To", "City", "Country", "Depart", "Return", "Source", "Book"):
        t.add_column(c)
    for d in dests[:limit]:
        t.add_row(f"{d.price:,.0f} {d.currency}", d.destination, d.city or "", d.country or "",
                  str(d.departure or ""), str(d.return_date or ""), d.source,
                  f"[link={d.booking_url}]open[/link]" if d.booking_url else "")
    out.print(t)


@app.command()
def dates(
    origin: str, destination: str,
    earliest: str = typer.Option("+7", "--from"),
    latest: str = typer.Option("+37", "--to"),
    trip_days: Optional[int] = typer.Option(None, "--trip-days", help="Round trip length"),
    currency: Optional[str] = typer.Option(None, "--currency", "-c"),
    as_json: bool = JsonOpt,
):
    """Cheapest price per departure date (Google Flights, one request per date)."""
    from .sources import google

    from .search import cheapest_per_day, direct_dates

    o, d = origin.upper(), destination.upper()
    with con.status("pricing dates..."):
        res = google.dates(o, d, _date(earliest), _date(latest), _cur(currency), trip_days)
        if not trip_days:  # airline calendars are one way only
            extra, errs = direct_dates(o, d, _date(earliest), _date(latest), _cur(currency))
            for n, e in errs.items():
                con.print(f"[yellow]{n} calendar failed: {e}[/yellow]")
            res = cheapest_per_day(res + extra)
    if as_json:
        return _emit_json([r.model_dump(mode="json") for r in res])
    lo = min((r.price for r in res), default=0)
    t = Table(title=f"{origin.upper()} to {destination.upper()} by date", header_style="bold")
    for c in ("Date", "Return", "Price", ""):
        t.add_column(c)
    for r in sorted(res, key=lambda r: r.departure):
        bar = "█" * max(1, int(20 * lo / r.price)) if r.price else ""
        t.add_row(r.departure.strftime("%a %d %b"), str(r.return_date or ""), f"{r.price:,.0f} {r.currency}",
                  f"[green]{bar}[/green]" if r.price == lo else bar)
    out.print(t)


@app.command("airports")
def airports_cmd(query: str, as_json: bool = JsonOpt):
    """Look up airports by code, city or name."""
    hits = airports.find(query)
    if as_json:
        return _emit_json([a.model_dump() for a in hits[:25]])
    for a in hits[:25]:
        out.print(f"{a.iata}  {a.name}, {a.city} ({a.country})")


# ---------------------------------------------------------------------------
# account / web app
# ---------------------------------------------------------------------------

@app.command()
def login(url: str = typer.Option(..., help="Your FlightScout site, e.g. https://flightscout.vercel.app"),
          token: str = typer.Option(..., help="API token from Settings, API tokens")):
    """Connect the CLI (and MCP server) to your web account."""
    config.save(api_url=url.rstrip("/"), token=token)
    try:
        me = Client().me()
        out.print(f"Logged in as {me.get('user', {}).get('email', 'unknown')}.")
    except Exception as e:
        con.print(f"[red]Saved, but the check failed: {e}[/red]")


@app.command()
def whoami(as_json: bool = JsonOpt):
    """Show the connected web account."""
    me = Client().me()
    if as_json:
        return _emit_json(me)
    out.print(me)


@app.command("open")
def open_cmd(page: str = typer.Argument("", help="search, explore, watchlist, places, history, settings")):
    """Open the web app in your browser."""
    base = config.load().get("api_url")
    if not base:
        raise typer.BadParameter("Not logged in. Run `flightscout login` first.")
    webbrowser.open(f"{base}/{page}".rstrip("/"))


@app.command("setup-browser")
def setup_browser():
    """Install the headless Chromium used for seller and fare breakdowns (--sellers)."""
    import subprocess

    try:
        import playwright  # noqa: F401
    except ImportError:
        con.print("[red]Playwright is missing. Reinstall with the browser extra: "
                  "uv tool install 'flightscout[browser] @ git+https://github.com/halvis82/FlightScout#subdirectory=engine'[/red]")
        raise typer.Exit(1)
    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
    out.print("Browser installed. Try: flightscout search JFK LAX +30 --sellers 3")


PLIST = "com.flightscout.runner"


@app.command()
def serve(port: int = typer.Option(8787), install: bool = typer.Option(False, "--install", help="Start automatically at login (macOS)"),
          uninstall: bool = typer.Option(False, "--uninstall")):
    """Run the local runner: the website sends searches here so they come from your own IP."""
    import os
    import shutil
    import subprocess
    from pathlib import Path

    plist = Path.home() / "Library" / "LaunchAgents" / f"{PLIST}.plist"
    if uninstall:
        subprocess.run(["launchctl", "unload", str(plist)], check=False)
        plist.unlink(missing_ok=True)
        out.print("Local runner removed from login items.")
        return
    if install:
        exe = shutil.which("flightscout") or sys.argv[0]
        log = Path.home() / "Library" / "Logs" / "flightscout-runner.log"
        plist.parent.mkdir(parents=True, exist_ok=True)
        plist.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{PLIST}</string>
  <key>ProgramArguments</key><array><string>{exe}</string><string>serve</string><string>--port</string><string>{port}</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>{log}</string>
  <key>StandardErrorPath</key><string>{log}</string>
</dict></plist>
""")
        subprocess.run(["launchctl", "unload", str(plist)], check=False, capture_output=True)
        subprocess.run(["launchctl", "load", str(plist)], check=True)
        out.print(f"Local runner installed. It starts at login on http://127.0.0.1:{port} (log: {log}).")
        return
    import uvicorn

    os.environ["FLIGHTSCOUT_LOCAL"] = "1"
    from .api import app as api_app

    out.print(f"FlightScout local runner on http://127.0.0.1:{port}. The website will use it automatically.")
    uvicorn.run(api_app, host="127.0.0.1", port=port, log_level="warning")


@app.command()
def mcp():
    """Run the MCP server on stdio (add to Claude Code with `claude mcp add flightscout -- flightscout mcp`)."""
    from .mcp_server import main

    main()


# ---------------------------------------------------------------------------
# watchlist
# ---------------------------------------------------------------------------

def _client() -> Client:
    c = Client()
    if not c.ready:
        con.print("[red]Not logged in. Run `flightscout login --url <site> --token <token>`.[/red]")
        raise typer.Exit(1)
    return c


@watch_app.command("list")
def watch_list(as_json: bool = JsonOpt):
    ws = _client().watches()
    if as_json:
        return _emit_json(ws)
    t = Table(header_style="bold")
    for c in ("ID", "Name", "Route", "Dates", "Best", "Checked", "Active"):
        t.add_column(c)
    for w in ws:
        dates_ = f"{w['depart_start']}..{w.get('depart_end') or ''}"
        if w.get("trip_type") == "roundtrip":
            dates_ += f" ({w.get('nights_min')}-{w.get('nights_max')}n)"
        best = f"{w['best_price']:,.0f} {w['currency']}" if w.get("best_price") else "-"
        t.add_row(w["id"][:8], w.get("name") or "", f"{','.join(w['origins'])} to {','.join(w['destinations'])}",
                  dates_, best, str(w.get("last_checked_at") or "never")[:16], "yes" if w.get("active", True) else "no")
    out.print(t)


@watch_app.command("add")
def watch_add(
    origin: str, destination: str,
    earliest: str = typer.Option(..., "--from", help="Earliest departure"),
    latest: Optional[str] = typer.Option(None, "--to", help="Latest departure"),
    nights: Optional[str] = typer.Option(None, help="Round trip nights MIN-MAX; omit for one way"),
    name: Optional[str] = typer.Option(None),
    alert_below: Optional[float] = typer.Option(None, "--alert-below"),
    alert_drop_pct: Optional[float] = typer.Option(10.0, "--alert-drop-pct"),
    split: bool = typer.Option(True, "--split/--no-split", help="Also track split ticket deals"),
    currency: Optional[str] = typer.Option(None, "--currency", "-c"),
    cabin: str = typer.Option("economy"),
    as_json: bool = JsonOpt,
):
    """Start tracking a route."""
    lo = hi = None
    if nights:
        a, _, b = nights.partition("-")
        lo, hi = int(a), int(b or a)
    w = _client().add_watch(
        name=name or f"{origin.upper()} to {destination.upper()}", origins=_codes(origin), destinations=_codes(destination),
        trip_type="roundtrip" if nights else "oneway", depart_start=_date(earliest).isoformat(),
        depart_end=_date(latest).isoformat() if latest else None, nights_min=lo, nights_max=hi,
        currency=_cur(currency), cabin=cabin, include_split=split, alert_below=alert_below,
        alert_drop_pct=alert_drop_pct,
    )
    if as_json:
        return _emit_json(w)
    out.print(f"Watching {w.get('name')} ({w['id']}).")


@watch_app.command("rm")
def watch_rm(watch_id: str):
    c = _client()
    wid = _resolve_watch(c, watch_id)
    c.delete_watch(wid)
    out.print("Removed.")


def _resolve_watch(c: Client, prefix: str) -> str:
    for w in c.watches():
        if w["id"].startswith(prefix):
            return w["id"]
    raise typer.BadParameter(f"no watch with id {prefix}")


@watch_app.command("check")
def watch_check(watch_id: Optional[str] = typer.Argument(None, help="Only this watch"),
                budget: int = typer.Option(12, help="Google searches per watch"),
                as_json: bool = JsonOpt):
    """Price every active watch now and push the results to the web app."""
    from .tracker import run_all

    c = _client()
    only = _resolve_watch(c, watch_id) if watch_id else None
    with con.status("checking watches..."):
        summary = run_all(c, only=only, budget=budget)
    if as_json:
        return _emit_json(summary)
    out.print(f"Checked {len(summary)} watch(es), {sum(summary.values())} observations saved.")


@watch_app.command("history")
def watch_history(watch_id: str, as_json: bool = JsonOpt):
    c = _client()
    h = c.history(_resolve_watch(c, watch_id))
    if as_json:
        return _emit_json(h)
    for o in h[-40:]:
        out.print(f"{str(o['observed_at'])[:16]}  {o['depart_date']}  {o.get('return_date') or '':10}  "
                  f"{o['price']:>9,.0f} {o['currency']}  {o['kind']:9} {o['route']}")


# ---------------------------------------------------------------------------
# places
# ---------------------------------------------------------------------------

@places_app.command("list")
def places_list(as_json: bool = JsonOpt):
    ps = _client().places()
    if as_json:
        return _emit_json(ps)
    for p in ps:
        out.print(f"{p['id'][:8]}  {p['kind']:10} {p['label']}: {','.join(p['codes'])}")


@places_app.command("add")
def places_add(label: str, codes: str, kind: str = typer.Option("interested", help="home, frequent, interested")):
    p = _client().add_place(label=label, codes=_codes(codes), kind=kind)
    out.print(f"Added {p['label']}.")


@places_app.command("rm")
def places_rm(place_id: str):
    c = _client()
    for p in c.places():
        if p["id"].startswith(place_id):
            c.delete_place(p["id"])
            out.print("Removed.")
            return
    raise typer.BadParameter("no such place")


@app.command()
def track(budget: int = typer.Option(12), verbose: bool = typer.Option(False, "-v")):
    """Tracker entry point for cron (uses FLIGHTSCOUT_TRACKER_KEY for all users)."""
    from .tracker import run_all

    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING, format="%(message)s")
    c = Client()
    if not c.ready:
        con.print("[red]Set FLIGHTSCOUT_API_URL and FLIGHTSCOUT_TRACKER_KEY (or login).[/red]")
        raise typer.Exit(1)
    summary = run_all(c, budget=budget)
    out.print(json.dumps(summary))


def main():
    try:
        app()
    except NotLoggedIn as e:
        con.print(f"[red]{e}[/red]")
        sys.exit(1)
