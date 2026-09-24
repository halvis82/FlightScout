"""Account and web app: login, settings, alerts, history, API tokens."""

from __future__ import annotations

from typing import Optional

import typer
from rich.table import Table

from .. import config
from ..client import Client
from .common import Fmt, FmtOpt, JsonOpt, client, con, emit_csv, emit_json, fmt_of, open_url, out

settings_app = typer.Typer(no_args_is_help=True, help="Account settings (same as the website's Settings page).")
alerts_app = typer.Typer(no_args_is_help=True, help="Price alerts from your watches.")
history_app = typer.Typer(no_args_is_help=True, help="Past searches from the website, CLI and agents.")
tokens_app = typer.Typer(no_args_is_help=True, help="API tokens for the CLI, MCP server and scripts.")
config_app = typer.Typer(no_args_is_help=True, help="Local CLI configuration (~/.config/flightscout/config.json).")


def register(app: typer.Typer) -> None:
    app.command(rich_help_panel="Account")(login)
    app.command(rich_help_panel="Account")(logout)
    app.command(rich_help_panel="Account")(whoami)
    app.command("open", rich_help_panel="Account")(open_cmd)
    for sub, name in ((settings_app, "settings"), (alerts_app, "alerts"), (history_app, "history"),
                      (tokens_app, "tokens"), (config_app, "config")):
        app.add_typer(sub, name=name, rich_help_panel="Account")


def login(url: str = typer.Option(..., help="Your FlightScout site, e.g. https://flightscout-app.vercel.app."),
          token: str = typer.Option(..., help="API token (website: Settings, API tokens).")):
    """Connect the CLI and MCP server to your account."""
    config.save(api_url=url.rstrip("/"), token=token)
    try:
        me = Client().me()
        out.print(f"Logged in as {me.get('user', {}).get('email', 'unknown')}. Results now show up on the website.")
    except Exception as e:
        con.print(f"[red]Saved, but the check failed: {e}[/red]")


def logout():
    """Forget the saved token."""
    cfg = config.load()
    cfg.pop("token", None)
    config.PATH.parent.mkdir(parents=True, exist_ok=True)
    import json

    config.PATH.write_text(json.dumps({k: v for k, v in cfg.items() if k != "token"}, indent=2))
    out.print("Logged out.")


def whoami(fmt: Fmt = FmtOpt, as_json: bool = JsonOpt):
    """Show the connected account and its settings."""
    me = client().me()
    if fmt_of(fmt, as_json) == Fmt.json:
        return emit_json(me)
    s = me.get("settings", {})
    out.print(f"{me.get('user', {}).get('email')} on {Client().base}")
    out.print(f"currency {s.get('currency')}, start searches from {', '.join(s.get('default_origins') or []) or 'last used'}")


def open_cmd(page: str = typer.Argument("", help="Page: search (default), airlines, settings, history.")):
    """Open the website in your browser."""
    base = config.load().get("api_url") or "https://flightscout-app.vercel.app"
    open_url(f"{base}/{page}".rstrip("/"))


# settings --------------------------------------------------------------------

@settings_app.command("show")
def settings_show(fmt: Fmt = FmtOpt, as_json: bool = JsonOpt):
    """Currency, default origin, smart route limits, seller rules and alert channels."""
    s = client().me().get("settings", {})
    if fmt_of(fmt, as_json) == Fmt.json:
        return emit_json(s)
    out.print(f"currency:            {s.get('currency')}")
    out.print(f"start searches from: {', '.join(s.get('default_origins') or []) or 'last used'}")
    out.print(f"email alerts:        {s.get('email_alerts')}   push alerts: {s.get('push_alerts')}")
    p = s.get("planner") or {}
    out.print("smart routes:        " + ", ".join(f"{k}={v}" for k, v in p.items()))
    rules = s.get("seller_rules") or []
    out.print("seller rules:        " + (", ".join(f"{r['seller']}={r['mode']}" for r in rules) or "none"))


@settings_app.command("set")
def settings_set(
    currency: Optional[str] = typer.Option(None, help="Display currency (NOK, EUR, USD, GBP, MXN...)."),
    default_from: Optional[str] = typer.Option(None, "--default-from", help="Airports to start searches from, or 'last'."),
    email_alerts: Optional[bool] = typer.Option(None, "--email-alerts/--no-email-alerts"),
    push_alerts: Optional[bool] = typer.Option(None, "--push-alerts/--no-push-alerts"),
    max_hubs: Optional[int] = typer.Option(None, "--max-hubs", help="Smart routes: hubs to try."),
    max_stopover_days: Optional[int] = typer.Option(None, "--max-stopover-days", help="Smart routes: longest stopover."),
    min_connection_hours: Optional[float] = typer.Option(None, "--min-connection", help="Smart routes: hours between tickets."),
    max_trip_days: Optional[int] = typer.Option(None, "--max-trip-days"),
):
    """Change settings (only the ones you pass)."""
    body: dict = {}
    if currency:
        body["currency"] = currency.upper()
        config.save(currency=currency.upper())
    if default_from is not None:
        body["defaultOrigins"] = [] if default_from.lower() == "last" else [c.strip().upper() for c in default_from.split(",")]
    if email_alerts is not None:
        body["emailAlerts"] = email_alerts
    if push_alerts is not None:
        body["pushAlerts"] = push_alerts
    planner = {k: v for k, v in {"max_hubs": max_hubs, "max_stopover_days": max_stopover_days,
                                  "min_connection_hours": min_connection_hours, "max_trip_days": max_trip_days}.items()
               if v is not None}
    if planner:
        body["planner"] = planner
    if not body:
        raise typer.BadParameter("nothing to change (see --help)")
    client()._req("PATCH", "/settings", json=body)
    out.print("Saved.")


@settings_app.command("seller")
def settings_seller(seller: str = typer.Argument(..., help="Seller name as shown in results, e.g. Kiwi.com or Gotogate."),
                    mode: str = typer.Argument(..., help="block (hide), warn (flag) or remove (drop the rule).")):
    """Block or flag a travel agency everywhere."""
    c = client()
    rules = [r for r in c.me().get("settings", {}).get("seller_rules") or [] if r["seller"].lower() != seller.lower()]
    if mode != "remove":
        if mode not in ("block", "warn"):
            raise typer.BadParameter("mode must be block, warn or remove")
        rules.append({"seller": seller, "mode": mode})
    c._req("PATCH", "/settings", json={"sellerRules": rules})
    out.print(f"{seller}: {mode}.")


# alerts ------------------------------------------------------------------------

@alerts_app.command("list")
def alerts_list(unread: bool = typer.Option(False, "--unread"), fmt: Fmt = FmtOpt, as_json: bool = JsonOpt):
    """Price drop alerts."""
    r = client()._req("GET", "/alerts")
    items = [a for a in r.get("alerts", []) if not unread or not a.get("read_at")]
    if fmt_of(fmt, as_json) == Fmt.json:
        return emit_json(items)
    if not items:
        out.print("No alerts.")
    for a in items:
        mark = " " if a.get("read_at") else "[bold green]●[/bold green]"
        out.print(f"{mark} {str(a['created_at'])[:16]}  {a['message']}")


@alerts_app.command("read")
def alerts_read(ids: list[int] = typer.Argument(None, help="Alert ids (default: all).")):
    """Mark alerts as read."""
    client()._req("POST", "/alerts", json={"ids": ids} if ids else {"all": True})
    out.print("Marked read.")


# history -----------------------------------------------------------------------

@history_app.command("list")
def history_list(limit: int = typer.Option(20), fmt: Fmt = FmtOpt, as_json: bool = JsonOpt):
    """Recent searches (website, CLI, agents)."""
    rows = client()._req("GET", f"/searches?limit={limit}")
    rows = rows.get("items", rows) if isinstance(rows, dict) else rows
    f = fmt_of(fmt, as_json)
    if f == Fmt.json:
        return emit_json(rows)
    flat = [{"id": r["id"], "when": str(r["created_at"])[:16], "kind": r["kind"], "from": r.get("origin"),
             "summary": r.get("summary") or ""} for r in rows]
    if f == Fmt.csv:
        return emit_csv(flat)
    t = Table(header_style="bold")
    for c in ("ID", "When", "Kind", "Via", "Summary"):
        t.add_column(c)
    for r in flat:
        t.add_row(str(r["id"]), r["when"], r["kind"], r["from"] or "", r["summary"])
    out.print(t)


@history_app.command("show")
def history_show(search_id: int, limit: int = typer.Option(15), fmt: Fmt = FmtOpt, as_json: bool = JsonOpt):
    """Show the results of a past search."""
    from ..models import Trip
    from .common import show_trips

    r = client()._req("GET", f"/searches/{search_id}")
    payload = r.get("payload") or {}
    if fmt_of(fmt, as_json) == Fmt.json:
        return emit_json(r)
    trips = [Trip(**t) for t in payload.get("trips", [])]
    if trips:
        return show_trips(trips, fmt_of(fmt, as_json), limit, r.get("summary") or f"Search {search_id}")
    for d in (payload.get("destinations") or payload.get("items") or [])[:limit]:
        out.print(f"{d.get('price'):>8,.0f} {d.get('currency')}  {d.get('destination')} {d.get('city') or ''}")


@history_app.command("rm")
def history_rm(search_id: int):
    """Delete a saved search."""
    client()._req("DELETE", f"/searches/{search_id}")
    out.print("Deleted.")


# tokens ------------------------------------------------------------------------

@tokens_app.command("list")
def tokens_list():
    """Your API tokens (only the prefix is shown)."""
    for t in client()._req("GET", "/tokens"):
        out.print(f"{t['id']:>4}  {t['name']:20} {t.get('prefix', '')}…  last used {str(t.get('last_used_at') or 'never')[:16]}")


@tokens_app.command("create")
def tokens_create(name: str = typer.Argument(..., help="e.g. laptop, agent, script.")):
    """Create a token (shown once)."""
    t = client()._req("POST", "/tokens", json={"name": name})
    out.print(f"{t['token']}\nStore it now; it won't be shown again.")


@tokens_app.command("revoke")
def tokens_revoke(token_id: int):
    """Revoke a token."""
    client()._req("DELETE", f"/tokens/{token_id}")
    out.print("Revoked.")


# local config ------------------------------------------------------------------

@config_app.command("show")
def config_show():
    """Print the local config (token hidden)."""
    cfg = config.load()
    if cfg.get("token"):
        cfg["token"] = cfg["token"][:8] + "…"
    emit_json(cfg)


@config_app.command("set")
def config_set(currency: Optional[str] = typer.Option(None, help="Default currency for CLI results."),
               url: Optional[str] = typer.Option(None, help="Website URL.")):
    """Set local defaults."""
    config.save(currency=currency.upper() if currency else None, api_url=url.rstrip("/") if url else None)
    out.print(f"Saved to {config.PATH}.")
