"""Local runner, MCP server, browser setup and the scheduled jobs."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import typer

from ..client import Client
from .common import con, out

PLIST = "com.flightscout.runner"


def register(app: typer.Typer) -> None:
    app.command(rich_help_panel="Run")(status)
    app.command(rich_help_panel="Run")(serve)
    app.command(rich_help_panel="Run")(mcp)
    app.command("setup-browser", rich_help_panel="Run")(setup_browser)
    app.command(rich_help_panel="Scheduled jobs")(track)
    app.command(rich_help_panel="Scheduled jobs")(warm)


TRACK_PLIST = "com.flightscout.track"


def _install_tracking(exe: str, env: str, log: Path) -> None:
    """Check the logged in user's watches at 07:00 and 19:00 from this Mac."""
    plist = Path.home() / "Library" / "LaunchAgents" / f"{TRACK_PLIST}.plist"
    times = "".join(f"<dict><key>Hour</key><integer>{h}</integer><key>Minute</key><integer>5</integer></dict>" for h in (7, 19))
    plist.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{TRACK_PLIST}</string>
  <key>ProgramArguments</key><array><string>{exe}</string><string>watch</string><string>check</string></array>
  <key>EnvironmentVariables</key><dict>{env}</dict>
  <key>StartCalendarInterval</key><array>{times}</array>
  <key>StandardOutPath</key><string>{log}</string>
  <key>StandardErrorPath</key><string>{log}</string>
</dict></plist>
""")
    subprocess.run(["launchctl", "unload", str(plist)], check=False, capture_output=True)
    subprocess.run(["launchctl", "load", str(plist)], check=True)


def serve(port: int = typer.Option(8787, help="Port (the website looks for 8787)."),
          install: bool = typer.Option(False, "--install", help="Start automatically at login (macOS)."),
          track: bool = typer.Option(True, "--track/--no-track",
                                     help="With --install: also check your watches at 07:05 and 19:05 from this Mac."),
          uninstall: bool = typer.Option(False, "--uninstall", help="Remove the login item and scheduled checks.")):
    """Local runner: the website sends searches to this computer so they come from your own IP."""
    plist = Path.home() / "Library" / "LaunchAgents" / f"{PLIST}.plist"
    if uninstall:
        for p in (plist, Path.home() / "Library" / "LaunchAgents" / f"{TRACK_PLIST}.plist"):
            subprocess.run(["launchctl", "unload", str(p)], check=False, capture_output=True)
            p.unlink(missing_ok=True)
        out.print("Local runner and scheduled watch checks removed.")
        return
    if install:
        exe = shutil.which("flightscout") or sys.argv[0]
        log = Path.home() / "Library" / "Logs" / "flightscout-runner.log"
        keep = [k for k in os.environ if k.startswith("FLIGHTSCOUT_") or k == "SERPAPI_KEY"]
        env = "".join(f"<key>{k}</key><string>{os.environ[k]}</string>" for k in keep)
        plist.parent.mkdir(parents=True, exist_ok=True)
        plist.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{PLIST}</string>
  <key>ProgramArguments</key><array><string>{exe}</string><string>serve</string><string>--port</string><string>{port}</string></array>
  <key>EnvironmentVariables</key><dict>{env}</dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>{log}</string>
  <key>StandardErrorPath</key><string>{log}</string>
</dict></plist>
""")
        subprocess.run(["launchctl", "unload", str(plist)], check=False, capture_output=True)
        subprocess.run(["launchctl", "load", str(plist)], check=True)
        out.print(f"Local runner installed: starts at login on http://127.0.0.1:{port} (log: {log}).")
        if track:
            if Client().token:
                _install_tracking(exe, env, Path.home() / "Library" / "Logs" / "flightscout-track.log")
                out.print("Your watches will also be checked at 07:05 and 19:05 from this Mac (your home IP).")
            else:
                con.print("[yellow]Not logged in, so watch checks weren't scheduled. Run `flightscout login`, "
                          "then `flightscout serve --install` again.[/yellow]")
        return
    import uvicorn

    os.environ["FLIGHTSCOUT_LOCAL"] = "1"
    from ..api import app as api_app

    out.print(f"FlightScout local runner on http://127.0.0.1:{port}. The website will use it automatically.")
    uvicorn.run(api_app, host="127.0.0.1", port=port, log_level="warning")


def status():
    """Login, local runner, scheduled watch checks and browser support at a glance."""
    import httpx

    c = Client()
    who = "not logged in (flightscout login)"
    if c.ready and c.token:
        try:
            who = f"{c.me().get('user', {}).get('email')} on {c.base}"
        except Exception as e:
            who = f"token rejected by {c.base}: {e}"
    try:
        h = httpx.get("http://127.0.0.1:8787/health", timeout=1.5).json()
        runner = f"running (version {h.get('version')})" if h.get("local") else "port 8787 is used by something else"
    except Exception:
        runner = "not running (flightscout serve --install)"
    la = Path.home() / "Library" / "LaunchAgents"
    try:
        import playwright  # noqa: F401
        browser = "installed (seller breakdowns, Google Explore)"
    except ImportError:
        browser = "not installed (optional: flightscout setup-browser)"
    rows = [("account", who), ("local runner", runner),
            ("starts at login", "yes" if (la / f"{PLIST}.plist").exists() else "no"),
            ("watch checks from this Mac", "07:05 and 19:05" if (la / f"{TRACK_PLIST}.plist").exists() else "no"),
            ("browser support", browser)]
    for k, v in rows:
        out.print(f"{k:28} {v}")


def mcp():
    """MCP server on stdio for AI agents: `claude mcp add flightscout -- flightscout mcp`."""
    from ..mcp_server import main

    main()


def setup_browser():
    """Install the headless Chromium used by --sellers and Google Explore."""
    try:
        import playwright  # noqa: F401
    except ImportError:
        con.print("[red]Playwright is missing. Reinstall with the browser extra: uv tool install "
                  "'flightscout[browser] @ git+https://github.com/halvis82/FlightScout#subdirectory=engine'[/red]")
        raise typer.Exit(1)
    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
    out.print("Browser installed. Try: flightscout search JFK LAX +30 --sellers 3")


def track(budget: int = typer.Option(12, help="Google searches per watch."), verbose: bool = typer.Option(False, "-v")):
    """Check every user's watches (GitHub Actions job; needs FLIGHTSCOUT_TRACKER_KEY)."""
    from ..tracker import run_all

    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING, format="%(message)s")
    c = Client()
    if not c.ready:
        con.print("[red]Set FLIGHTSCOUT_API_URL and FLIGHTSCOUT_TRACKER_KEY (or log in).[/red]")
        raise typer.Exit(1)
    out.print(json.dumps(run_all(c, budget=budget)))


def warm(currency: str = typer.Option("USD"), verbose: bool = typer.Option(False, "-v")):
    """Pre-compute explore results for everyone's home airports into the shared cache (GitHub Actions job)."""
    from ..explore import explore as run_explore

    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING, format="%(message)s")
    c = Client()
    for o in c.tracker_origins()[:25]:
        start = date.today() + timedelta(days=7)
        try:
            dests, errors = run_explore(o, start, start + timedelta(days=60), currency, (4, 10),
                                        sources=["google", "kiwiweb", "kayak", "ryanair"], regions=["anywhere"])
        except Exception as e:
            con.print(f"[yellow]{o}: {e}[/yellow]")
            continue
        c.tracker_explore(o, currency, [d.model_dump(mode="json") for d in dests])
        out.print(f"{o}: {len(dests)} destinations {errors or ''}")
