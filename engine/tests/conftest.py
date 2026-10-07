"""Offline by default. Live tests (real sources on the internet) run with
FLIGHTSCOUT_LIVE=1 or `pytest -m live`."""

import json
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


# Airline and booking sites wall off datacenter IPs (GitHub runners) with
# 403s, Cloudflare/Akamai/Kasada pages or empty answers, while they work from
# home. On CI such a live failure is reported as a skip, so the nightly stays
# green; anywhere else (run the live tests from home before changing a
# source) it still fails. Real breakage (parse errors, wrong data) fails
# everywhere.
_WALLED = ("403", "429", "forbidden", "security verification", "just a moment", "access denied", "captcha",
           "unusual traffic", "rate_limited", "no availability response", "blocked", "cloudflare", "akamai",
           # silent walls: these sites answer GitHub's servers with nothing (checked from home on
           # 2026-09-26: Avelo, United, VietJet, Akasa, Tigerair, Traveloka and Cleartrip all passed)
           "no search response", "no flights response", "no search-flight response", "no flight search response",
           "did not create a session token", "err_http_response_code_failure",
           # a wall page where the site's API answers JSON (Porter, passed from home the same day)
           "unexpected token '<'",
           # the connection is reset before any answer (LEVEL on GitHub's servers, passed from home 2026-09-26)
           "reset by server",
           # Southwest's shopping call and Zipair's results page answer GitHub's servers with nothing
           # (both passed from home 2026-10-06; "no flights" is matched only for Zipair on purpose)
           "no shopping response", "zipair_browser: no flights")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    if (rep.when == "call" and rep.failed and "live" in item.keywords and os.environ.get("GITHUB_ACTIONS")
            and call.excinfo is not None):
        text = str(call.excinfo.value).lower()
        if any(w in text for w in _WALLED):
            rep.outcome = "skipped"
            rep.longrepr = (str(item.path), item.location[1] or 0, f"walled on CI: {text.splitlines()[0][:160]}")


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


# Two strikes on CI. The nightly asks about 70 real sites from GitHub's
# datacenter IPs; each fails now and then for reasons of its own (a bot wall
# that day, a slow answer), so one run almost always had some red test while
# every source worked. The workflow retries a failed live test once
# (pytest-rerunfailures), and FLIGHTSCOUT_LIVE_STATE keeps the tests that still
# failed. A live test that fails in one run is a warning; failing again in the
# next run (a source that really broke) turns the run red.
_final_failures: set[str] = set()


def pytest_runtest_logreport(report):
    if report.failed and "live" in report.keywords:  # retried attempts report as "rerun", not failed
        _final_failures.add(report.nodeid)


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    state = os.environ.get("FLIGHTSCOUT_LIVE_STATE")
    if not (state and os.environ.get("GITHUB_ACTIONS")):
        return
    path = Path(state)
    try:
        before = set(json.loads(path.read_text()))
    except (OSError, ValueError):
        before = set()
    path.write_text(json.dumps(sorted(_final_failures)))
    again = _final_failures & before
    once = _final_failures - before
    lines = []
    for n in sorted(again):
        print(f"::error title=Live source failed twice in a row::{n}")
        lines.append(f"- ❌ `{n}` failed in this run and the one before: probably broken")
    for n in sorted(once):
        print(f"::warning title=Live source failed once (retried)::{n}")
        lines.append(f"- ⚠️ `{n}` failed once (after a retry): red if it fails again next run")
    if lines and os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write("### Live source failures\n" + "\n".join(lines) + "\n")
    # only live test failures can be forgiven, and only first ones
    others = session.testsfailed > len(_final_failures)
    if exitstatus == pytest.ExitCode.TESTS_FAILED and not again and not others:
        session.exitstatus = pytest.ExitCode.OK
