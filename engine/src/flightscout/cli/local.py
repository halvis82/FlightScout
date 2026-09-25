"""The whole FlightScout on this computer, running only while you use it.

`flightscout local install` prepares the website from a clone of the repo and
lets the system (launchd on macOS, systemd on Linux) listen on
http://localhost:3000. Opening that address in a browser starts the site (and
the engine, on 8787, when a search needs it); a minute or two after the last
FlightScout tab is closed both stop again. Nothing runs in between.

The open page pings the site every 30 s (and the engine every 60 s), so "in
use" means "a FlightScout tab is open"."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import typer

from .common import con, out

CONF = Path(os.environ.get("FLIGHTSCOUT_HOME", Path.home() / ".config" / "flightscout"))
SITE_JSON = CONF / "site.json"
SITE_PLIST = "com.flightscout.site"
IDLE_S = 150  # the page pings every 30 s (at most once a minute in a background tab)

local_app = typer.Typer(help="The whole FlightScout on this computer, running only while it's open in your browser.",
                        no_args_is_help=True)


def _conf() -> dict:
    if not SITE_JSON.exists():
        con.print("[red]Not installed yet: run the install script or `flightscout local install`.[/red]")
        raise typer.Exit(1)
    return json.loads(SITE_JSON.read_text())


def _secret() -> str:
    p = CONF / "local-secret"
    if not p.exists():
        CONF.mkdir(parents=True, exist_ok=True)
        p.write_text(secrets.token_hex(32))
        p.chmod(0o600)
    return p.read_text().strip()


def _site_env(c: dict) -> dict[str, str]:
    """Settings the local website runs with (never written into the repo)."""
    web = Path(c["repo"]) / "web"
    env = {
        "BETTER_AUTH_SECRET": _secret(),
        "BETTER_AUTH_URL": f"http://localhost:{c['port']}",
        "ENGINE_URL": "http://127.0.0.1:8787",
        "ENGINE_KEY": "local",
        "TRACKER_KEY": "local-" + _secret()[:16],
        "FLIGHTSCOUT_NO_RATE_LIMIT": "1",
        "NODE_ENV": "production",
        "NEXT_TELEMETRY_DISABLED": "1",
    }
    if c["mode"] == "shared":
        for line in (CONF / "local.env").read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"')
        env["NEXT_PUBLIC_OPEN_SIGNUP"] = "0"
    else:
        env.update({"DATABASE_URL": f"pglite:{web / '.pglite'}", "ALLOWED_SIGNUP_EMAILS": "*",
                    "NEXT_PUBLIC_OPEN_SIGNUP": "1"})
    return env


def _node(c: dict) -> tuple[str, str]:
    node = c.get("node") or shutil.which("node")
    if not node:
        con.print("[red]Node.js 22+ is needed (the install script sets it up).[/red]")
        raise typer.Exit(1)
    npm = str(Path(node).with_name("npm"))
    return node, npm if Path(npm).exists() else (shutil.which("npm") or "npm")


def _build(c: dict) -> None:
    web = Path(c["repo"]) / "web"
    node, npm = _node(c)
    env = {**os.environ, **_site_env(c), "PATH": f"{Path(node).parent}:{os.environ.get('PATH', '')}"}
    out.print("Installing the website's packages (first time takes a minute)")
    subprocess.run([npm, "ci", "--no-audit", "--no-fund", "--loglevel=error"], cwd=web, env=env, check=True)
    out.print("Building the website")
    subprocess.run([npm, "run", "-s", "build"], cwd=web, env=env, check=True)  # also applies database migrations
    (web / ".next" / "fs-mode").write_text(c["mode"])


# --- the launcher the system starts when the browser opens the site ---------

def _run_site(listen: socket.socket, c: dict) -> None:
    """Start the website behind `listen` and pass traffic through; stop when
    nothing has gone through for IDLE_S (no FlightScout tab open)."""
    web = Path(c["repo"]) / "web"
    node, _ = _node(c)
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    inner = s.getsockname()[1]
    s.close()
    env = {**os.environ, **_site_env(c), "PATH": f"{Path(node).parent}:{os.environ.get('PATH', '')}"}
    proc = subprocess.Popen([node, str(web / "node_modules" / "next" / "dist" / "bin" / "next"), "start",
                             "-p", str(inner), "-H", "127.0.0.1"], cwd=web, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    last = [time.time()]

    async def pipe(r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        try:
            while data := await r.read(65536):
                last[0] = time.time()
                w.write(data)
                await w.drain()
        except (ConnectionError, OSError):
            pass
        finally:
            try:
                w.close()
            except Exception:
                pass

    async def handle(cr: asyncio.StreamReader, cw: asyncio.StreamWriter) -> None:
        last[0] = time.time()
        for _ in range(240):  # the site takes a few seconds to start
            try:
                sr, sw = await asyncio.open_connection("127.0.0.1", inner)
                break
            except OSError:
                await asyncio.sleep(0.25)
        else:
            cw.close()
            return
        await asyncio.gather(pipe(cr, sw), pipe(sr, cw))

    async def main() -> None:
        server = await asyncio.start_server(handle, sock=listen)
        async with server:
            while time.time() - last[0] < IDLE_S and proc.poll() is None:
                await asyncio.sleep(5)

    if c["mode"] == "own":  # nobody else checks your watches: do it while the site is open
        threading.Thread(target=_track_if_due, args=(inner, env["TRACKER_KEY"]), daemon=True).start()
    try:
        asyncio.run(main())
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def _track_if_due(port: int, key: str) -> None:
    stamp = CONF / "last-track"
    if stamp.exists() and time.time() - stamp.stat().st_mtime < 12 * 3600:
        return
    time.sleep(20)  # let the site start
    exe = shutil.which("flightscout") or sys.argv[0]
    env = {**os.environ, "FLIGHTSCOUT_API_URL": f"http://127.0.0.1:{port}", "FLIGHTSCOUT_TRACKER_KEY": key}
    if subprocess.run([exe, "track"], env=env, capture_output=True).returncode == 0:
        stamp.touch()


# --- commands ---------------------------------------------------------------

def _install_socket(port: int) -> Path:
    exe = shutil.which("flightscout") or sys.argv[0]
    if sys.platform == "darwin":
        plist = Path.home() / "Library" / "LaunchAgents" / f"{SITE_PLIST}.plist"
        log = Path.home() / "Library" / "Logs" / "flightscout-site.log"
        plist.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{SITE_PLIST}</string>
  <key>ProgramArguments</key><array><string>{exe}</string><string>local</string><string>site</string></array>
  <key>EnvironmentVariables</key><dict><key>FLIGHTSCOUT_LAUNCHD</key><string>1</string></dict>
  <key>Sockets</key><dict><key>Listeners</key><dict>
    <key>SockNodeName</key><string>127.0.0.1</string>
    <key>SockServiceName</key><string>{port}</string>
    <key>SockType</key><string>stream</string>
  </dict></dict>
  <key>StandardOutPath</key><string>{log}</string>
  <key>StandardErrorPath</key><string>{log}</string>
</dict></plist>
""")
        plist.chmod(0o600)
        subprocess.run(["launchctl", "unload", str(plist)], check=False, capture_output=True)
        subprocess.run(["launchctl", "load", str(plist)], check=True)
        return plist
    d = Path.home() / ".config" / "systemd" / "user"
    d.mkdir(parents=True, exist_ok=True)
    (d / "flightscout-site.socket").write_text(
        f"[Unit]\nDescription=FlightScout website (on demand)\n\n[Socket]\nListenStream=127.0.0.1:{port}\n\n"
        "[Install]\nWantedBy=sockets.target\n")
    (d / "flightscout-site.service").write_text(
        f"[Unit]\nDescription=FlightScout website\n\n[Service]\nExecStart={exe} local site\n")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    subprocess.run(["systemctl", "--user", "enable", "--now", "flightscout-site.socket"], check=True)
    return d / "flightscout-site.socket"


@local_app.command()
def install(repo: Path = typer.Option(..., help="Your clone of the FlightScout repo."),
            shared: bool = typer.Option(False, "--shared", help="Use the online site's accounts and watchlist "
                                        "(its database address in ~/.config/flightscout/local.env)."),
            node: str = typer.Option("", help="Path to node (default: the one on PATH)."),
            port: int = typer.Option(3000, help="Port for the website.")):
    """Set up the website on this computer: it starts when you open http://localhost:3000 and stops a couple of
    minutes after you close it."""
    repo = repo.expanduser().resolve()
    if not (repo / "web" / "package.json").exists():
        con.print(f"[red]{repo} is not a FlightScout clone (no web/package.json).[/red]")
        raise typer.Exit(1)
    if shared and not (CONF / "local.env").exists():
        con.print("[red]--shared needs ~/.config/flightscout/local.env with DATABASE_URL=... (the online site's "
                  "database address).[/red]")
        raise typer.Exit(1)
    CONF.mkdir(parents=True, exist_ok=True)
    c = {"repo": str(repo), "mode": "shared" if shared else "own", "port": port,
         "node": node or shutil.which("node") or ""}
    SITE_JSON.write_text(json.dumps(c, indent=1))
    _build(c)
    if sys.platform == "darwin" or (sys.platform.startswith("linux") and shutil.which("systemctl")):
        where = _install_socket(port)
        from .system import serve
        serve(port=8787, install=True, idle=3, track=False, uninstall=False)  # the engine, same way
        out.print(f"\nDone ({where}). Open http://localhost:{port} : it starts in a few seconds, and it stops a "
                  "couple of minutes after you close the last FlightScout tab. Nothing runs in between.")
    else:
        out.print(f"\nDone. Run `flightscout local start` and open http://localhost:{port} (it stops when you close "
                  "the tab).")


@local_app.command()
def update():
    """Get the latest FlightScout and rebuild the local website."""
    c = _conf()
    subprocess.run(["git", "-C", c["repo"], "pull", "--ff-only"], check=True)
    _build(c)
    out.print("Updated.")


@local_app.command()
def start(port: int = typer.Option(0, help="Port (default: the installed one, 3000).")):
    """Run the local website now in this terminal (for Windows, or without the on demand setup). It stops by itself a
    couple of minutes after the last FlightScout tab is closed, or with Ctrl+C."""
    c = _conf()
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", port or c["port"]))
    sock.listen(64)
    out.print(f"FlightScout on http://localhost:{port or c['port']}")
    _run_site(sock, c)


@local_app.command("site", hidden=True)
def site():
    """Started by the system when the browser opens the site (socket activation)."""
    from .system import _activated_socket

    fd = _activated_socket()
    if fd is None:
        con.print("[red]Not started by the system: use `flightscout local start`.[/red]")
        raise typer.Exit(1)
    _run_site(socket.socket(fileno=fd), _conf())


@local_app.command()
def status():
    """Whether the local website is set up, and in which mode."""
    if not SITE_JSON.exists():
        out.print("Not set up (see `flightscout local install --help`).")
        return
    c = json.loads(SITE_JSON.read_text())
    running = subprocess.run(["pgrep", "-f", "flightscout local site"], capture_output=True).returncode == 0
    out.print(f"Local website: http://localhost:{c['port']} ({'your own data' if c['mode'] == 'own' else 'shared with the online site'}), "
              f"from {c['repo']}. {'Open right now.' if running else 'Not running (starts when you open it).'}")


@local_app.command()
def uninstall():
    """Remove the on demand local website (your data in the repo's web/.pglite stays)."""
    p = Path.home() / "Library" / "LaunchAgents" / f"{SITE_PLIST}.plist"
    if p.exists():
        subprocess.run(["launchctl", "unload", str(p)], check=False, capture_output=True)
        p.unlink()
    d = Path.home() / ".config" / "systemd" / "user"
    if (d / "flightscout-site.socket").exists():
        subprocess.run(["systemctl", "--user", "disable", "--now", "flightscout-site.socket"], check=False)
        for n in ("flightscout-site.socket", "flightscout-site.service"):
            (d / n).unlink(missing_ok=True)
    SITE_JSON.unlink(missing_ok=True)
    out.print("Local website removed. The engine runner stays (remove it with `flightscout serve --uninstall`).")
