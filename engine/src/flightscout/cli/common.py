"""Shared CLI plumbing: consoles, argument parsing, output (table, JSON,
CSV), filters and sorting, and saving results to the web account."""

from __future__ import annotations

import csv
import json
import sys
import webbrowser
from datetime import date, timedelta
from enum import Enum
from typing import Iterable, Optional

import typer
from rich.console import Console
from rich.table import Table

from .. import config
from ..client import Client

con = Console(stderr=True)  # progress, notes, errors
out = Console()  # results


class Fmt(str, Enum):
    table = "table"
    json = "json"
    csv = "csv"


class Sort(str, Enum):
    price = "price"
    duration = "duration"
    departure = "departure"
    best = "best"


FmtOpt = typer.Option(Fmt.table, "--format", "-f", help="table (default), json (for agents and scripts) or csv.")
JsonOpt = typer.Option(False, "--json", help="Shortcut for --format json.")
SaveOpt = typer.Option(True, "--save/--no-save", help="Save the result to your web account (History) when logged in.")
CurOpt = typer.Option(None, "--currency", "-c", help="NOK, EUR, USD, GBP, MXN... Default: your configured currency.")


def fmt_of(fmt: Fmt, as_json: bool) -> Fmt:
    return Fmt.json if as_json else fmt


def cur(c: Optional[str]) -> str:
    return (c or config.load().get("currency") or "USD").upper()


def parse_date(s: str) -> date:
    """YYYY-MM-DD, today, tomorrow, +N (days from today), or a weekday like fri
    (the next one)."""
    s = s.strip().lower()
    if s == "today":
        return date.today()
    if s == "tomorrow":
        return date.today() + timedelta(days=1)
    if s.startswith("+") and s[1:].isdigit():
        return date.today() + timedelta(days=int(s[1:]))
    days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    if s[:3] in days:
        ahead = (days.index(s[:3]) - date.today().weekday()) % 7 or 7
        return date.today() + timedelta(days=ahead)
    return date.fromisoformat(s)


def codes(s: str) -> list[str]:
    return [c.strip().upper() for c in s.split(",") if c.strip()]


def nights_range(s: Optional[str]) -> Optional[tuple[int, int]]:
    if not s:
        return None
    lo, _, hi = s.partition("-")
    return int(lo), int(hi or lo)


def emit_json(obj) -> None:
    if hasattr(obj, "model_dump"):
        obj = obj.model_dump(mode="json")
    sys.stdout.write(json.dumps(obj, indent=2, default=str) + "\n")


def emit_csv(rows: Iterable[dict]) -> None:
    rows = list(rows)
    if not rows:
        return
    w = csv.DictWriter(sys.stdout, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)


def save(kind: str, query: dict, payload, enabled: bool) -> None:
    if not enabled:
        return
    c = Client()
    if not c.ready or not c.token:
        return
    try:
        c.save_result(kind, query, payload.model_dump(mode="json") if hasattr(payload, "model_dump") else payload)
        con.print(f"[dim]saved to {c.base}/history[/dim]")
    except Exception as e:
        con.print(f"[yellow]could not save to the web app: {e}[/yellow]")


def client() -> Client:
    c = Client()
    if not c.ready:
        con.print("[red]Not logged in. Run `flightscout login --url <site> --token <token>` "
                  "(token from Settings, API tokens on the site).[/red]")
        raise typer.Exit(1)
    return c


def open_url(url: str) -> None:
    con.print(f"[dim]opening {url[:90]}...[/dim]")
    webbrowser.open(url)


def fmt_min(m: int) -> str:
    return f"{m // 60}h{m % 60:02d}"


# ---------------------------------------------------------------------------
# trips: filter, sort, render
# ---------------------------------------------------------------------------

def filter_sort(trips, sort: Sort = Sort.price, max_price: Optional[float] = None, max_stops: Optional[int] = None,
                time_of_day: Optional[str] = None, hide_self_transfer: bool = False, airline: Optional[str] = None):
    def stops(t):
        return max(sl.stops for tk in t.tickets for sl in tk.slices) + len(t.tickets) - 1

    def ok(t):
        if max_price is not None and t.total_price > max_price:
            return False
        if max_stops is not None and stops(t) > max_stops:
            return False
        if hide_self_transfer and any(tk.self_transfer for tk in t.tickets):
            return False
        if airline and not any(airline.upper() in sl.carriers for tk in t.tickets for sl in tk.slices):
            return False
        if time_of_day:
            h = t.departure.hour
            if time_of_day == "morning" and not 5 <= h < 12:
                return False
            if time_of_day == "afternoon" and not 12 <= h < 18:
                return False
            if time_of_day == "evening" and 5 <= h < 18:
                return False
        return True

    kept = [t for t in trips if ok(t)]
    if sort == Sort.duration:
        return sorted(kept, key=lambda t: t.travel_min)
    if sort == Sort.departure:
        return sorted(kept, key=lambda t: t.departure)
    if sort == Sort.best:
        return sorted(kept, key=lambda t: t.score if t.score is not None else t.total_price + 15 * t.travel_min / 60)
    return sorted(kept, key=lambda t: t.total_price)


def trip_rows(trips) -> list[dict]:
    rows = []
    for i, t in enumerate(trips, 1):
        rows.append({
            "n": i, "price": t.total_price, "currency": t.currency, "kind": t.kind, "tickets": len(t.tickets),
            "route": "-".join(t.route), "depart": t.departure.isoformat(), "arrive": t.arrival.isoformat(),
            "travel": fmt_min(t.travel_min),
            "airlines": ",".join(sorted({c for tk in t.tickets for sl in tk.slices for c in sl.carriers})),
            "sources": ",".join(sorted({tk.source for tk in t.tickets})),
            "self_transfer": any(tk.self_transfer for tk in t.tickets),
            "return_pending": any(tk.return_pending for tk in t.tickets),
            "savings_vs_direct": t.savings_vs_direct, "note": t.note or "",
            "booking_urls": " ".join(tk.booking_url for tk in t.tickets),
        })
    return rows


def trips_table(trips, limit: int, title: str) -> Table:
    t = Table(title=title, header_style="bold")
    for col in ("#", "Price", "Kind", "Route", "Depart", "Arrive", "Travel", "Airlines", "Book"):
        t.add_column(col, overflow="fold")
    for i, tr in enumerate(trips[:limit], 1):
        carriers = sorted({c for tk in tr.tickets for sl in tk.slices for c in sl.carriers})
        kind = tr.kind + (f" ({len(tr.tickets)} tickets)" if len(tr.tickets) > 1 else "")
        if tr.stopovers:
            kind += " " + ", ".join(f"{s.airport} {s.hours / 24:.1f}d" if s.hours >= 24 else f"{s.airport} {s.hours:.0f}h"
                                    for s in tr.stopovers)
        if any(tk.self_transfer for tk in tr.tickets):
            kind += " [yellow]self transfer[/yellow]"
        if any(tk.return_pending for tk in tr.tickets):
            kind = "round trip [dim](pick return on Google)[/dim]"
        if tr.note:
            kind += f"\n[yellow]{tr.note}[/yellow]"
        links = "\n".join(f"[link={tk.booking_url}]{tk.seller or tk.source}[/link]" for tk in tr.tickets)
        price = f"{tr.total_price:,.0f} {tr.currency}"
        if tr.savings_vs_direct and tr.savings_vs_direct > 0:
            price += f"\n[green]saves {tr.savings_vs_direct:,.0f}[/green]"
        t.add_row(str(i), price, kind, "-".join(tr.route), tr.departure.strftime("%a %d %b %H:%M"),
                  tr.arrival.strftime("%a %d %b %H:%M"), fmt_min(tr.travel_min), ",".join(carriers), links)
    return t


def show_trips(trips, fmt: Fmt, limit: int, title: str, payload=None) -> None:
    if fmt == Fmt.json:
        return emit_json(payload if payload is not None else {"trips": [t.model_dump(mode="json") for t in trips]})
    if fmt == Fmt.csv:
        return emit_csv(trip_rows(trips[:limit]))
    if not trips:
        out.print("No flights match. Try --flex, --nearby, fewer filters, or `flightscout plan` for split tickets.")
        return
    out.print(trips_table(trips, limit, title))
