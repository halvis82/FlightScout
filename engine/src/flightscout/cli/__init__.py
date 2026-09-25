"""`flightscout` command line. Tables for people, `--format json` / `--json`
for agents and scripts, `--format csv` for spreadsheets. When logged in, results
are saved to your account and show up on the website (History).

Full reference: docs/CLI.md (generated from this code)."""

from __future__ import annotations

import sys

import typer

from ..client import NotLoggedIn
from . import account, flights, places_cmds, system
from .common import con
from .common import parse_date as _date  # noqa: F401  (kept for older imports and tests)
from .lists import places_app, watch_app

app = typer.Typer(
    no_args_is_help=True,
    pretty_exceptions_enable=False,
    add_completion=True,
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
    help="FlightScout: find flights across Google Flights, Kiwi.com and airlines directly, build cheaper routes "
         "from separate tickets, explore cheap destinations and track prices.\n\n"
         "Dates accept YYYY-MM-DD, today, tomorrow, +N (days from today) or a weekday (fri). Airports accept "
         "codes, comma lists (OSL,TRF) and metros (NYC, LON, BAY, OSLX...).",
)
flights.register(app)
places_cmds.register(app)
app.add_typer(watch_app, name="watch", rich_help_panel="Track")
app.add_typer(places_app, name="places", rich_help_panel="Track")
account.register(app)
system.register(app)


def main() -> None:
    from pydantic import ValidationError

    try:
        app()
    except NotLoggedIn as e:
        con.print(f"[red]{e}[/red]")
        sys.exit(1)
    except ValidationError as e:
        # "the departure date ... is in the past" instead of a traceback
        msgs = [err.get("msg", "").removeprefix("Value error, ") for err in e.errors()]
        con.print("[red]" + "; ".join(dict.fromkeys(msgs)) + "[/red]")
        sys.exit(2)
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:  # network down, a source changed...: one clear line, no traceback
        con.print(f"[red]{type(e).__name__}: {e}[/red]")
        if "--debug" in sys.argv:
            raise
        sys.exit(1)
