"""Watchlist and saved places."""

from __future__ import annotations

from typing import Optional

import typer
from rich.table import Table

from .common import CurOpt, Fmt, FmtOpt, JsonOpt, client, codes, con, cur, emit_csv, emit_json, fmt_of, open_url, out, parse_date

watch_app = typer.Typer(no_args_is_help=True, help="Watchlist: routes tracked twice a day, with price history and alerts.")
places_app = typer.Typer(no_args_is_help=True, help="Saved places: homes, favorites and places you want to go.")


def _resolve(c, prefix: str) -> int:
    for w in c.watches():
        if str(w["id"]) == str(prefix) or str(w["id"]).startswith(str(prefix)):
            return w["id"]
    raise typer.BadParameter(f"no watch with id {prefix} (see `flightscout watch list`)")


@watch_app.command("list")
def watch_list(fmt: Fmt = FmtOpt, as_json: bool = JsonOpt):
    """All watches with current best price and when they were last checked."""
    ws = client().watches()
    f = fmt_of(fmt, as_json)
    if f == Fmt.json:
        return emit_json([{k: v for k, v in w.items() if k != "best_trip"} for w in ws])
    rows = [{"id": w["id"], "name": w.get("name"), "route": f"{','.join(w['origins'])} to {','.join(w['destinations'])}",
             "dates": f"{w['depart_start']}..{w.get('depart_end') or ''}"
             + (f" ({w.get('nights_min')}-{w.get('nights_max')} nights)" if w.get("trip_type") == "roundtrip" else ""),
             "best": w.get("best_price"), "low": w.get("lowest_price"), "currency": w.get("currency"),
             "checked": str(w.get("last_checked_at") or "never")[:16], "active": w.get("active", True)} for w in ws]
    if f == Fmt.csv:
        return emit_csv(rows)
    if not rows:
        out.print("No watches yet. Add one: flightscout watch add SAN OSL --from 2026-12-15 --to 2026-12-20 --nights 10-14")
        return
    t = Table(header_style="bold")
    for c in ("ID", "Name", "Route", "Dates", "Best", "All time low", "Checked", "Active"):
        t.add_column(c)
    for r in rows:
        t.add_row(str(r["id"]), r["name"] or "", r["route"], r["dates"],
                  f"{r['best']:,.0f} {r['currency']}" if r["best"] else "-", f"{r['low']:,.0f}" if r["low"] else "-",
                  r["checked"], "yes" if r["active"] else "paused")
    out.print(t)


@watch_app.command("add")
def watch_add(
    origin: str = typer.Argument(..., help="From (airports or metro)."),
    destination: str = typer.Argument(..., help="To (airports or metro)."),
    earliest: str = typer.Option(..., "--from", help="Earliest departure."),
    latest: Optional[str] = typer.Option(None, "--to", help="Latest departure (default: same as --from)."),
    nights: Optional[str] = typer.Option(None, help="Round trip length MIN-MAX nights; omit for one way."),
    name: Optional[str] = typer.Option(None, help="Label shown in the watchlist."),
    alert_below: Optional[float] = typer.Option(None, "--alert-below", help="Alert when a price drops below this."),
    alert_drop_pct: Optional[float] = typer.Option(10.0, "--alert-drop-pct", help="Alert on a drop of this % vs the best so far."),
    split: bool = typer.Option(True, "--split/--no-split", help="Also track split ticket deals."),
    cabin: str = typer.Option("economy"),
    adults: int = typer.Option(1),
    currency: Optional[str] = CurOpt,
    fmt: Fmt = FmtOpt,
    as_json: bool = JsonOpt,
):
    """Start tracking a route.

    Examples:
      flightscout watch add SAN OSL --from 2026-12-15 --to 2026-12-20 --nights 10-14 --alert-below 900
      flightscout watch add OSL LON --from +14 --to +60 --nights 2-3 --name "London weekend"
    """
    lo = hi = None
    if nights:
        a, _, b = nights.partition("-")
        lo, hi = int(a), int(b or a)
    w = client().add_watch(
        name=name or f"{origin.upper()} to {destination.upper()}", origins=codes(origin), destinations=codes(destination),
        trip_type="roundtrip" if nights else "oneway", depart_start=parse_date(earliest).isoformat(),
        depart_end=parse_date(latest or earliest).isoformat(), nights_min=lo, nights_max=hi, currency=cur(currency),
        cabin=cabin, adults=adults, include_split=split, alert_below=alert_below, alert_drop_pct=alert_drop_pct,
    )
    if fmt_of(fmt, as_json) == Fmt.json:
        return emit_json(w)
    if w.get("existing"):
        out.print(f"Already watching {w.get('name')} (id {w['id']}). Nothing new was created.")
    else:
        out.print(f"Watching {w.get('name')} (id {w['id']}). Run `flightscout watch check {w['id']}` for prices now.")


@watch_app.command("edit")
def watch_edit(
    watch_id: str,
    name: Optional[str] = typer.Option(None),
    earliest: Optional[str] = typer.Option(None, "--from"),
    latest: Optional[str] = typer.Option(None, "--to"),
    nights: Optional[str] = typer.Option(None),
    alert_below: Optional[float] = typer.Option(None, "--alert-below"),
    alert_drop_pct: Optional[float] = typer.Option(None, "--alert-drop-pct"),
    currency: Optional[str] = typer.Option(None, "--currency", "-c"),
):
    """Change a watch's dates, trip length, alerts or name."""
    c = client()
    body: dict = {}
    if name is not None:
        body["name"] = name
    if earliest:
        body["depart_start"] = parse_date(earliest).isoformat()
    if latest:
        body["depart_end"] = parse_date(latest).isoformat()
    if nights:
        a, _, b = nights.partition("-")
        body.update(nights_min=int(a), nights_max=int(b or a), trip_type="roundtrip")
    if alert_below is not None:
        body["alert_below"] = alert_below
    if alert_drop_pct is not None:
        body["alert_drop_pct"] = alert_drop_pct
    if currency:
        body["currency"] = currency.upper()
    if not body:
        raise typer.BadParameter("nothing to change (see --help)")
    c.update_watch(_resolve(c, watch_id), **body)
    out.print("Updated.")


@watch_app.command("pause")
def watch_pause(watch_id: str):
    """Stop checking a watch (keeps its history)."""
    c = client()
    c.update_watch(_resolve(c, watch_id), active=False)
    out.print("Paused.")


@watch_app.command("resume")
def watch_resume(watch_id: str):
    """Start checking a paused watch again."""
    c = client()
    c.update_watch(_resolve(c, watch_id), active=True)
    out.print("Resumed.")


@watch_app.command("rm")
def watch_rm(watch_id: str, yes: bool = typer.Option(False, "--yes", "-y", help="Don't ask.")):
    """Delete a watch and its history."""
    c = client()
    wid = _resolve(c, watch_id)
    if not yes and not typer.confirm(f"Delete watch {wid} and its price history?"):
        raise typer.Exit()
    c.delete_watch(wid)
    out.print("Deleted.")


@watch_app.command("check")
def watch_check(watch_id: Optional[str] = typer.Argument(None, help="Only this watch (default: all active)."),
                budget: int = typer.Option(12, help="Google searches per watch."),
                server: bool = typer.Option(False, "--server", help="Let the website's server check it (like its Check now)."),
                fmt: Fmt = FmtOpt, as_json: bool = JsonOpt):
    """Price watches now from this computer (your IP) and save the results."""
    from ..tracker import run_all

    c = client()
    only = _resolve(c, watch_id) if watch_id else None
    if server:
        ids = [only] if only else [w["id"] for w in c.watches() if w.get("active", True)]
        with con.status("checking on the server..."):
            res = {i: c._req("POST", f"/watches/{i}/check") for i in ids}
        if fmt_of(fmt, as_json) == Fmt.json:
            return emit_json(res)
        out.print(f"Checked {len(ids)} watch(es) on the server.")
        return
    with con.status("checking watches..."):
        summary = run_all(c, only=only, budget=budget)
    if fmt_of(fmt, as_json) == Fmt.json:
        return emit_json(summary)
    out.print(f"Checked {len(summary)} watch(es), {sum(summary.values())} prices saved.")


@watch_app.command("history")
def watch_history(watch_id: str, limit: int = typer.Option(40), fmt: Fmt = FmtOpt, as_json: bool = JsonOpt):
    """Every price seen for a watch, oldest first, with a trend line."""
    c = client()
    h = c.history(_resolve(c, watch_id))
    f = fmt_of(fmt, as_json)
    if f == Fmt.json:
        return emit_json([{k: v for k, v in o.items() if k != "trip"} for o in h])
    rows = [{"seen": str(o["observed_at"])[:16], "depart": o["depart_date"], "return": o.get("return_date") or "",
             "price": o["price"], "currency": o["currency"], "kind": o["kind"], "route": o["route"], "source": o["source"]}
            for o in h]
    if f == Fmt.csv:
        return emit_csv(rows)
    t = Table(header_style="bold")
    for col in ("Seen", "Depart", "Return", "Price", "Kind", "Route"):
        t.add_column(col)
    for r in rows[-limit:]:
        t.add_row(r["seen"], r["depart"], r["return"], f"{r['price']:,.0f} {r['currency']}", r["kind"], r["route"])
    out.print(t)
    daily: dict[str, float] = {}
    for r in rows:
        daily[r["seen"][:10]] = min(daily.get(r["seen"][:10], float("inf")), r["price"])
    if len(daily) > 1:
        vals = list(daily.values())
        lo, hi = min(vals), max(vals)
        bars = "▁▂▃▄▅▆▇█"
        out.print("Daily low: " + "".join(bars[int((v - lo) / (hi - lo or 1) * 7)] for v in vals)
                  + f"  {vals[0]:,.0f} → {vals[-1]:,.0f}")


@watch_app.command("open")
def watch_open(watch_id: str):
    """Open the watch's page on the website."""
    c = client()
    open_url(f"{c.base}/watches/{_resolve(c, watch_id)}")


@places_app.command("list")
def places_list(fmt: Fmt = FmtOpt, as_json: bool = JsonOpt):
    """Your homes, favorites and want-to-go places."""
    ps = client().places()
    f = fmt_of(fmt, as_json)
    if f == Fmt.json:
        return emit_json(ps)
    if f == Fmt.csv:
        return emit_csv([{"id": p["id"], "label": p["label"], "codes": ",".join(p["codes"]), "kind": p["kind"]} for p in ps])
    for p in ps:
        out.print(f"{p['id']:>4}  {p['kind']:10} {p['label']}: {', '.join(p['codes'])}")


@places_app.command("add")
def places_add(label: str = typer.Argument(..., help="Name, e.g. Home or Paris."),
               codes_: str = typer.Argument(..., metavar="CODES", help="Airports, comma separated (SAN or OSL,TRF)."),
               kind: str = typer.Option("frequent", help="home, frequent (favorite) or interested (want to go).")):
    """Save a place (shows as a one click chip on the website)."""
    p = client().add_place(label=label, codes=codes(codes_), kind=kind)
    if p.get("existing"):
        out.print(f"Already saved as {p['label']} ({', '.join(p['codes'])}).")
    else:
        out.print(f"Added {p['label']} ({', '.join(p['codes'])}).")


@places_app.command("star")
def places_star(code: str = typer.Argument(..., help="Airport code to favorite, e.g. LIS."),
                kind: str = typer.Option("frequent", help="frequent (favorite), home or interested (want to go).")):
    """Favorite an airport in one step (labelled with its city), like the star on the website."""
    from .. import airports as ap

    a = ap.get(code)
    if not a:
        raise typer.BadParameter(f"unknown airport {code}")
    p = client().add_place(label=a.city, codes=[a.iata], kind=kind)
    out.print(("Already a favorite: " if p.get("existing") else "Starred ") + f"{a.city} ({a.iata}).")


@places_app.command("set")
def places_set(place_id: int, kind: Optional[str] = typer.Option(None, help="home, frequent or interested."),
               label: Optional[str] = typer.Option(None)):
    """Change a place's kind or label."""
    body = {k: v for k, v in {"kind": kind, "label": label}.items() if v}
    client()._req("PATCH", f"/places/{place_id}", json=body)
    out.print("Updated.")


@places_app.command("rm")
def places_rm(place_id: int):
    """Remove a saved place."""
    client().delete_place(str(place_id))
    out.print("Removed.")
