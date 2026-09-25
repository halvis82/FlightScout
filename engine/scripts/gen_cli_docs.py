"""Generate docs/CLI.md from the CLI itself, so the reference never drifts.

    uv run python scripts/gen_cli_docs.py          # write
    uv run python scripts/gen_cli_docs.py --check  # exit 1 if out of date (CI)
"""

from __future__ import annotations

import sys
from pathlib import Path

import click
import typer.main

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from flightscout.cli import app  # noqa: E402

OUT = Path(__file__).resolve().parents[2] / "docs" / "CLI.md"

GUIDE = """# FlightScout CLI

The `flightscout` command does everything the website does, plus a few things only a terminal can: CSV and JSON
output for scripts and agents, seller and fare breakdowns from a real browser, and the local runner.

The CLI and the website share one engine (the Python package in `engine/`): the CLI runs it on your computer, the
website calls the same engine on Vercel. When you're logged in, every CLI search is saved to your account and shows up
on the website's History, and the watchlist, places, settings and alerts are the same everywhere.

## Install

```sh
uv tool install --python 3.12 'flightscout[browser] @ git+https://github.com/halvis82/FlightScout#subdirectory=engine'
flightscout setup-browser                     # optional: headless Chromium for --sellers and Google Explore
flightscout login --url https://flightscout-app.vercel.app --token fsk_...   # token: website, Settings, API tokens
flightscout --install-completion              # optional: tab completion
```

Update with the same `uv tool install ... --force` command.

## Conventions

| Thing | Accepted values |
|---|---|
| Dates | `2026-11-20`, `today`, `tomorrow`, `+14` (days from today), `fri` (the next Friday) |
| Airports | codes (`SAN`), lists (`OSL,TRF`), metros: `NYC` `LON` `PAR` `TYO` `CHI` `WAS` `MIL` `ROM` `STO` `OSLX` (OSL, TRF, RYG) `BAY` (SFO, OAK, SJC) `LAXX` (LA area) `MEX` `SEL` `SAO` `BUE` `YTO` `MIA` `HOU` `DFW` `BKK` `SHA` `BJS` `IST` |
| Currency | `-c NOK`, `-c EUR`, `-c USD`, `-c GBP`, `-c MXN` (any ISO code works); default from `flightscout config set --currency` |
| Output | table (default), `--format json` or `--json` (agents, scripts), `--format csv` (spreadsheets) |
| Saving | results are saved to your account when logged in; `--no-save` to skip |
| Links | every result has a booking link; `--open N` opens result N in your browser |

## Recipes

```sh
# Weekend away from Oslo under 1,500 NOK, one command
flightscout explore OSL --weekend --max-price 1500 -c NOK

# Christmas home: flexible dates, cheapest first, include cheaper separate ticket combos
flightscout search SAN OSL 2026-12-18 -r 2027-01-04 --depart-flex 3 --return-flex 2 --smart

# Nonstop mornings only, open the best result
flightscout search SFO JFK +30 --max-stops 0 --time morning --open 1

# Positioning and split tickets: San Diego to Bali via LAX, SFO, Asian hubs
flightscout plan SAN DPS 2027-02-11 -r 2027-02-22

# Multi city with a deadline: be in Paris by Nov 15
flightscout multicity SAN JFK@2026-11-03~2 OSL@2026-11-07~3 CDG@by2026-11-15 SAN@2026-11-20~1

# Cheapest day to fly this month (Google + airline + Skyscanner calendars)
flightscout dates TIJ GDL --from 2026-11-01 --to 2026-11-30 -c MXN

# Who sells it and what the fare includes (bags, changes, refunds)
flightscout search JFK LAX +30 --sellers 3

# Watch straight from a search (same as the website's button; saving twice is a no-op)
flightscout search SAN OSL 2026-12-18 -r 2027-01-04 --watch
flightscout multicity SAN JFK@2026-11-03~2 SAN@2026-11-10~1 --watch

# Airline sites for the flights you found, pre-filled
flightscout search OSL CPH 2026-11-20 --airline-links

# Everything at a glance: login, local runner, scheduled checks
flightscout status

# Track a route, get alerts, see the trend
flightscout watch add SAN OSL --from 2026-12-15 --to 2026-12-20 --nights 10-14 --alert-below 900
flightscout watch check && flightscout watch history 1

# Straight to an airline's own search, pre-filled
flightscout airlines --route OSL-CPH -d 2026-11-20 -r 2026-11-27 --open SK

# Scripts and agents
flightscout search OSL LON +21 --json | jq '.trips[0].tickets[0].booking_url'
flightscout explore SAN --format csv > destinations.csv
```

## AI agents (MCP)

```sh
claude mcp add flightscout -- flightscout mcp
```

Tools: `search_flights`, `plan_routes`, `multicity_trip`, `build_trip`, `explore_destinations`, `price_calendar`,
`find_airports`, `airline_links`, `list_watches`, `add_watch`, `check_watch`, `watch_history`, `list_places`. Agents can also call any command below with `--json`.

## Local runner

`flightscout serve --install` starts the engine at login on `127.0.0.1:8787`. The website detects it and sends your
searches through your own home IP instead of Vercel's servers (more reliable, and it can run Google Explore live).

---

# Command reference

Generated from the code by `engine/scripts/gen_cli_docs.py`. Run `flightscout <command> --help` for the same text.
"""


def _param_rows(cmd: click.Command) -> list[str]:
    rows = []
    for p in cmd.params:
        if p.name in ("help",) or getattr(p, "hidden", False):
            continue
        if p.param_type_name == "argument":
            name = f"`{p.human_readable_name.upper()}`"
            help_ = getattr(p, "help", "") or ""
            req = "required" if p.required else "optional"
            rows.append(f"| {name} | argument, {req} | {help_} |")
        else:
            names = ", ".join(f"`{o}`" for o in p.opts + p.secondary_opts)
            default = p.default
            if hasattr(default, "value"):
                default = default.value
            d = "" if default in (None, False, "", ()) or p.is_flag and default is False else f"`{default}`"
            kind = "flag" if p.is_flag else (p.type.name if hasattr(p.type, "name") else "")
            if isinstance(p.type, click.Choice):
                kind = " \\| ".join(p.type.choices)
            rows.append(f"| {names} | {kind}{' (default ' + d + ')' if d else ''} | {(p.help or '').replace('|', '/')} |")
    return rows


def _render(cmd: click.Command, path: str, level: int) -> list[str]:
    lines = [f"{'#' * level} `flightscout {path}`", ""]
    help_ = (cmd.help or "").strip()
    if help_:
        body, _, examples = help_.partition("Examples:")
        lines += [body.strip().replace("\n\n", "\n\n"), ""]
        if examples.strip():
            lines += ["```sh", *[ln.strip() for ln in examples.strip().splitlines() if ln.strip()], "```", ""]
    if isinstance(cmd, click.Group):
        for name, sub in cmd.commands.items():
            lines += _render(sub, f"{path} {name}", level + 1)
        return lines
    rows = _param_rows(cmd)
    if rows:
        lines += ["| Argument / option | Type | Description |", "|---|---|---|", *rows, ""]
    return lines


def generate() -> str:
    root = typer.main.get_command(app)
    order = ["search", "plan", "multicity", "trip", "dates", "explore", "airports", "airlines", "watch", "places",
             "login", "logout", "whoami", "open", "settings", "alerts", "history", "tokens", "config",
             "serve", "mcp", "setup-browser", "track", "warm"]
    names = order + [n for n in root.commands if n not in order]
    lines = [GUIDE]
    for n in names:
        if n in root.commands:
            lines += _render(root.commands[n], n, 2)
    return "\n".join(lines).rstrip() + "\n"


if __name__ == "__main__":
    text = generate()
    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text() != text:
            print("docs/CLI.md is out of date: run `uv run python scripts/gen_cli_docs.py`")
            sys.exit(1)
        print("docs/CLI.md is up to date")
    else:
        OUT.write_text(text)
        print(f"wrote {OUT} ({len(text.splitlines())} lines)")
