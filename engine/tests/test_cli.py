import csv
import io
import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import click
import pytest
import typer.main
from conftest import ticket
from typer.testing import CliRunner

from flightscout import search as search_mod
from flightscout.cli import app

runner = CliRunner()
ROOT = typer.main.get_command(app)


def _all_commands(group=ROOT, prefix=()):
    for name, cmd in group.commands.items():
        yield prefix + (name,)
        if isinstance(cmd, click.Group):
            yield from _all_commands(cmd, prefix + (name,))


@pytest.mark.parametrize("path", list(_all_commands()), ids=lambda p: " ".join(p))
def test_every_command_has_working_help(path):
    r = runner.invoke(app, [*path, "--help"])
    assert r.exit_code == 0, r.output
    assert "Usage" in r.output


def test_docs_are_up_to_date():
    script = Path(__file__).resolve().parents[1] / "scripts" / "gen_cli_docs.py"
    r = subprocess.run([sys.executable, str(script), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.fixture
def fake_sources(monkeypatch, dt):
    cheap = ticket(["SAN", "LAX"], dt.replace(hour=7), price=80, carrier="AS")
    pricey = ticket(["SAN", "LAX"], dt.replace(hour=19), price=300, carrier="DL")
    selft = ticket(["SAN", "SFO", "LAX"], dt.replace(hour=13), price=60, carrier="UA", self_transfer=True,
                   source="kiwi").model_copy(update={"seller_kind": "ota"})
    monkeypatch.setattr(search_mod, "SOURCES", {"google": lambda q: [cheap, pricey], "kiwi": lambda q: [selft]})
    monkeypatch.setattr(search_mod.google, "search_url", lambda q: "https://www.google.com/travel/flights")
    return dt


def test_search_json_filters_and_sorting(fake_sources):
    d = fake_sources.date().isoformat()
    r = runner.invoke(app, ["search", "SAN", "LAX", d, "--sources", "google,kiwi", "--json", "--no-save"])
    trips = json.loads(r.output)["trips"]
    assert [t["total_price"] for t in trips] == [60, 80, 300]  # cheapest first
    r = runner.invoke(app, ["search", "SAN", "LAX", d, "--sources", "google,kiwi", "--json", "--no-save",
                            "--max-price", "200", "--no-self-transfer", "--time", "morning"])
    assert [t["total_price"] for t in json.loads(r.output)["trips"]] == [80]


def test_search_csv_has_booking_links(fake_sources):
    d = fake_sources.date().isoformat()
    r = runner.invoke(app, ["search", "SAN", "LAX", d, "--sources", "google,kiwi", "-f", "csv", "--no-save"])
    rows = list(csv.DictReader(io.StringIO(r.output)))
    assert len(rows) == 3 and all(row["booking_urls"].startswith("https://") for row in rows)


def test_weekend_preset_picks_friday_to_sunday(monkeypatch):
    seen = {}

    def fake(q, rules=None):
        seen["q"] = q
        return search_mod.SearchResult(query=q, trips=[])

    monkeypatch.setattr("flightscout.search.search", fake)
    runner.invoke(app, ["search", "OSL", "CPH", "2026-10-06", "--preset", "weekend", "--no-save", "--json"])
    q = seen["q"]
    assert q.departure == date(2026, 10, 9) and q.return_date == date(2026, 10, 11)
    assert q.departure_flex_days == 1 and q.return_flex_days == 1


def test_multicity_leg_parsing(monkeypatch):
    got = {}

    def fake(req):
        got["req"] = req
        from flightscout.planner import PlanResult
        return PlanResult(trips=[])

    monkeypatch.setattr("flightscout.multicity.plan_multicity", fake)
    base = date.today() + timedelta(days=40)
    a, b = base.isoformat(), (base + timedelta(days=10)).isoformat()
    runner.invoke(app, ["multicity", "SAN", f"JFK@{a}~2", f"CDG@by{b}", "--no-save", "--json"])
    legs = got["req"].legs
    assert legs[0].origins == ["SAN"] and legs[0].before == 2 and legs[0].after == 2
    assert legs[1].origins == ["JFK"] and legs[1].arrive_by == base + timedelta(days=10) and legs[1].before == 10


def test_airlines_route_links():
    r = runner.invoke(app, ["airlines", "--route", "OSL-CPH", "-d", "2026-11-20", "-r", "2026-11-27", "--json"])
    rows = json.loads(r.output)
    sas = next(x for x in rows if x["iata"] == "SK")
    assert sas["prefilled"] and "OSL-CPH-20261120-20261127" in sas["url"]


def test_airports_nearby():
    r = runner.invoke(app, ["airports", "SAN", "--nearby", "150", "--json"])
    assert "TIJ" in [a["iata"] for a in json.loads(r.output)]
