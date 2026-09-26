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


def _x(v) -> str:
    """Text for a plist: a value with & or < must not break launchctl load."""
    from xml.sax.saxutils import escape

    return escape(str(v))


def write_private(path: Path, text: str) -> None:
    """Write a file only its owner can read, from the first byte (it may hold
    keys from the environment)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    path.chmod(0o600)


def _install_tracking(exe: str, env: str, log: Path) -> None:
    """Check the logged in user's watches at 07:00 and 19:00 from this Mac."""
    plist = Path.home() / "Library" / "LaunchAgents" / f"{TRACK_PLIST}.plist"
    times = "".join(f"<dict><key>Hour</key><integer>{h}</integer><key>Minute</key><integer>5</integer></dict>" for h in (7, 19))
    write_private(plist, f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{TRACK_PLIST}</string>
  <key>ProgramArguments</key><array><string>{_x(exe)}</string><string>watch</string><string>check</string></array>
  <key>EnvironmentVariables</key><dict>{env}</dict>
  <key>StartCalendarInterval</key><array>{times}</array>
  <key>StandardOutPath</key><string>{_x(log)}</string>
  <key>StandardErrorPath</key><string>{_x(log)}</string>
</dict></plist>
""")
    subprocess.run(["launchctl", "unload", str(plist)], check=False, capture_output=True)
    subprocess.run(["launchctl", "load", str(plist)], check=True)


def _activated_socket() -> int | None:
    """The listening socket handed over by launchd (macOS) or systemd (Linux)
    when the runner is started on demand, else None."""
    if os.environ.get("LISTEN_PID") == str(os.getpid()) and int(os.environ.get("LISTEN_FDS", "0")) >= 1:
        return 3  # systemd socket activation
    if sys.platform == "darwin" and os.environ.get("FLIGHTSCOUT_LAUNCHD") == "1":
        import ctypes

        libc = ctypes.CDLL("/usr/lib/libSystem.dylib")
        fds = ctypes.POINTER(ctypes.c_int)()
        count = ctypes.c_size_t(0)
        if libc.launch_activate_socket(b"Listeners", ctypes.byref(fds), ctypes.byref(count)) == 0 and count.value:
            return fds[0]
    return None


def _install_macos(exe: str, port: int, idle: int) -> Path:
    """launchd listens on the port and starts the runner on the first request;
    the runner exits after ``idle`` quiet minutes. Nothing runs in between."""
    plist = Path.home() / "Library" / "LaunchAgents" / f"{PLIST}.plist"
    log = Path.home() / "Library" / "Logs" / "flightscout-runner.log"
    keep = [k for k in os.environ if k.startswith("FLIGHTSCOUT_") and k != "FLIGHTSCOUT_LAUNCHD"] + \
        [k for k in ("SERPAPI_KEY", "SEARCHAPI_KEY") if k in os.environ]
    env = "".join(f"<key>{_x(k)}</key><string>{_x(os.environ[k])}</string>" for k in keep)
    write_private(plist, f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{PLIST}</string>
  <key>ProgramArguments</key><array><string>{_x(exe)}</string><string>serve</string><string>--idle</string><string>{idle}</string></array>
  <key>EnvironmentVariables</key><dict><key>FLIGHTSCOUT_LAUNCHD</key><string>1</string>{env}</dict>
  <key>Sockets</key><dict><key>Listeners</key><dict>
    <key>SockNodeName</key><string>127.0.0.1</string>
    <key>SockServiceName</key><string>{port}</string>
    <key>SockType</key><string>stream</string>
  </dict></dict>
  <key>StandardOutPath</key><string>{_x(log)}</string>
  <key>StandardErrorPath</key><string>{_x(log)}</string>
</dict></plist>
""")
    subprocess.run(["launchctl", "unload", str(plist)], check=False, capture_output=True)
    subprocess.run(["launchctl", "load", str(plist)], check=True)
    return plist


def _install_linux(exe: str, port: int, idle: int) -> Path:
    """systemd --user socket activation: same on demand behavior."""
    d = Path.home() / ".config" / "systemd" / "user"
    d.mkdir(parents=True, exist_ok=True)
    (d / "flightscout-runner.socket").write_text(
        f"[Unit]\nDescription=FlightScout local runner (on demand)\n\n[Socket]\nListenStream=127.0.0.1:{port}\n\n"
        "[Install]\nWantedBy=sockets.target\n")
    (d / "flightscout-runner.service").write_text(
        f"[Unit]\nDescription=FlightScout local runner\n\n[Service]\nExecStart={exe} serve --idle {idle}\n")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    subprocess.run(["systemctl", "--user", "enable", "--now", "flightscout-runner.socket"], check=True)
    return d / "flightscout-runner.socket"


def _uninstall() -> list[str]:
    done = []
    for p in (Path.home() / "Library" / "LaunchAgents" / f"{PLIST}.plist",
              Path.home() / "Library" / "LaunchAgents" / f"{TRACK_PLIST}.plist"):
        if p.exists():
            subprocess.run(["launchctl", "unload", str(p)], check=False, capture_output=True)
            p.unlink(missing_ok=True)
            done.append(str(p))
    d = Path.home() / ".config" / "systemd" / "user"
    if (d / "flightscout-runner.socket").exists():
        subprocess.run(["systemctl", "--user", "disable", "--now", "flightscout-runner.socket"], check=False)
        for n in ("flightscout-runner.socket", "flightscout-runner.service"):
            (d / n).unlink(missing_ok=True)
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
        done.append(str(d / "flightscout-runner.socket"))
    return done


def serve(port: int = typer.Option(8787, help="Port (the website looks for 8787)."),
          install: bool = typer.Option(False, "--install",
                                       help="Start on demand: the system listens on the port and starts the "
                                            "runner when the website calls it (macOS launchd, Linux systemd). "
                                            "Nothing runs while you're not searching."),
          idle: int = typer.Option(0, "--idle", help="Exit after this many minutes without searches (0 = never). "
                                   "--install uses 10."),
          track: bool = typer.Option(False, "--track/--no-track",
                                     help="With --install on macOS: also check your watches at 07:05 and 19:05 "
                                          "from this Mac (a few minutes twice a day)."),
          uninstall: bool = typer.Option(False, "--uninstall", help="Remove the on demand runner and scheduled checks.")):
    """Local runner: the website sends searches to this computer, so they come from your own IP and can use the
    browser read airlines and booking sites. Runs only while you use it."""
    if uninstall:
        done = _uninstall()
        out.print("Removed: " + ", ".join(done) if done else "Nothing was installed.")
        return
    if install:
        exe = shutil.which("flightscout") or sys.argv[0]
        mins = idle or 10
        if sys.platform == "darwin":
            where = _install_macos(exe, port, mins)
        elif sys.platform.startswith("linux") and shutil.which("systemctl"):
            where = _install_linux(exe, port, mins)
        else:
            con.print("[yellow]On demand start needs macOS or Linux with systemd. Run `flightscout serve` "
                      "while you search instead.[/yellow]")
            raise typer.Exit(1)
        out.print(f"Local runner ready on http://127.0.0.1:{port}: it starts when the website searches and "
                  f"stops after {mins} quiet minutes ({where}). Remove with `flightscout serve --uninstall`.")
        if track and sys.platform == "darwin":
            if Client().token:
                _install_tracking(exe, "", Path.home() / "Library" / "Logs" / "flightscout-track.log")
                out.print("Your watches will also be checked at 07:05 and 19:05 from this Mac.")
            else:
                con.print("[yellow]Not logged in, so watch checks weren't scheduled. Run `flightscout login`, "
                          "then `flightscout serve --install --track`.[/yellow]")
        return
    import threading
    import time

    import uvicorn

    os.environ["FLIGHTSCOUT_LOCAL"] = "1"
    from .. import api as api_mod

    fd = _activated_socket()
    config = uvicorn.Config(api_mod.app, host="127.0.0.1", port=port, fd=fd, log_level="warning")
    server = uvicorn.Server(config)
    if idle:
        # Health checks don't count: only searches keep the runner awake.
        def watch_idle() -> None:
            while not server.should_exit:
                time.sleep(15)
                if time.time() - api_mod.last_activity() > idle * 60:
                    server.should_exit = True

        threading.Thread(target=watch_idle, daemon=True).start()
    if fd is None:
        out.print(f"FlightScout local runner on http://127.0.0.1:{port}. The website uses it automatically"
                  + (f"; exits after {idle} quiet minutes." if idle else "; Ctrl+C to stop."))
    server.run()


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
            ("starts on demand", "yes" if (la / f"{PLIST}.plist").exists() else "no"),
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
