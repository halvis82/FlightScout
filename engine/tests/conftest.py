"""Offline by default. Live tests (real sources on the internet) run with
FLIGHTSCOUT_LIVE=1 or `pytest -m live`."""

import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("FLIGHTSCOUT_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("FLIGHTSCOUT_CONFIG", str(tmp_path / "config.json"))
    from flightscout import cache

    monkeypatch.setattr(cache, "DIR", tmp_path / "cache")


def pytest_collection_modifyitems(config, items):
    live = os.environ.get("FLIGHTSCOUT_LIVE") == "1" or "live" in (config.getoption("-m") or "")
    if live:
        return
    skip = pytest.mark.skip(reason="live test: set FLIGHTSCOUT_LIVE=1")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


FIXTURES = Path(__file__).parent / "fixtures"


def seg(o, d, dep, arr, carrier="XX", num="1"):
    from flightscout.models import Segment

    return Segment(origin=o, destination=d, departure=dep, arrival=arr, carrier=carrier, flight_number=num,
                   duration_min=int((arr - dep).total_seconds() // 60))


def ticket(route, dep, hours=3, price=100.0, source="google", carrier="XX", self_transfer=False, back=None):
    """Build an Itinerary along ``route`` (list of airports) leaving at ``dep``.
    ``back`` adds a return slice leaving at that datetime."""
    from flightscout.models import Itinerary, Slice

    def slice_(r, start):
        segs, t = [], start
        for i, (a, b) in enumerate(zip(r, r[1:])):
            segs.append(seg(a, b, t, t + timedelta(hours=hours), carrier, str(i + 1)))
            t = t + timedelta(hours=hours + 1)
        return Slice(segments=segs, duration_min=int((segs[-1].arrival - segs[0].departure).total_seconds() // 60))

    slices = [slice_(route, dep)]
    if back:
        slices.append(slice_(list(reversed(route)), back))
    return Itinerary(source=source, price=price, currency="USD", slices=slices, booking_url="https://example.com",
                     self_transfer=self_transfer)


@pytest.fixture
def d():
    return date.today() + timedelta(days=30)


@pytest.fixture
def dt():
    base = date.today() + timedelta(days=30)
    return datetime(base.year, base.month, base.day, 8, 0)
