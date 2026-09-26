"""Write docs/SOURCES.md from the source registry in search.py (run after
adding a source: `uv run python scripts/gen_sources_doc.py`)."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

from flightscout import search as s

GROUPS = [
    ("Google Flights, Kiwi", ["google", "kiwi", "kiwiweb"], "server, extension (Google) or local runner"),
    ("Airlines direct, plain HTTP", s.AIRLINES, "server or local runner"),
    ("Airlines direct, headless Chrome", list(s.BROWSER_SOURCES), "local runner only"),
    ("Booking sites, plain HTTP", list(s.OTAS), "server or local runner"),
    ("Booking sites, headless Chrome", list(s.OTAS_BROWSER), "local runner only"),
    ("Fare calendars", list(s.CALENDARS), "server or local runner (browser ones local only)"),
]


# Tried and ruled out, with the evidence (update when a site changes).
NOT_ADDED = [
    ("easyJet", "2026-09-26: every API path answers an Akamai challenge (HTTP 429 `cpr_chlge`) or \"Access Denied\" "
                "with Chrome and Safari TLS fingerprints, and its search page shows \"Access Denied\" to headless Chrome. "
                "Google Flights and Kiwi both sell easyJet fares."),
    ("Wizz Air search", "Its availability search sits behind Kasada and answers 429 even to a headless browser. Its "
                        "low fare calendar is used (`wizzair` calendar), and Google Flights and Kiwi sell Wizz fares."),
    ("Omio", "`omio_browser` works, but its results JSON prices were about 16% above what its own page showed on every "
             "comparison (2026-09), so it stays off until that's explained (FLIGHTSCOUT_OMIO_UNVERIFIED=1 turns it on)."),
    ("Ryanair availability API", "Its booking API answers \"Availability declined\" to non browser clients; the fare "
                                 "finder (the cheapest flight of each day, verified against the site) is used instead."),
]


def first_line(name: str) -> str:
    mod = None
    for cand in (name, f"{name}_browser"):  # the source's own module by name first
        try:
            mod = importlib.import_module(f"flightscout.sources.{cand}")
            break
        except ImportError:
            pass
    if mod is None:
        fn = s.SOURCES.get(name)
        mod = importlib.import_module(fn.__module__) if fn else s.CALENDARS.get(name)
    doc = (mod.__doc__ or "").strip().split("\n\n")[0].replace("\n", " ") if mod else ""
    return doc[:220] + ("..." if len(doc) > 220 else "")


def main() -> None:
    lines = ["# Sources", "", "Generated from `engine/src/flightscout/search.py` by `engine/scripts/gen_sources_doc.py`. "
             "Every source's prices were checked against that site's own booking page when it was added; the live "
             "tests (`FLIGHTSCOUT_LIVE=1 uv run pytest -m live`) keep checking them.", ""]
    total = 0
    for title, names, where in GROUPS:
        lines += [f"## {title} ({len(names)})", "", f"Runs on: {where}.", "", "| Source | Notes |", "|---|---|"]
        for n in names:
            lines.append(f"| `{n}` | {first_line(n).replace('|', '/')} |")
            total += 1
        lines.append("")
    lines += ["## Checked and not added", "",
              "Sites that were tried and can't be searched reliably today, so nobody tries them blindly again.", "",
              "| Site | What we found |", "|---|---|"]
    lines += [f"| {site} | {why} |" for site, why in NOT_ADDED]
    lines.append("")
    out = Path(__file__).resolve().parents[2] / "docs" / "SOURCES.md"
    out.write_text("\n".join(lines))
    print(f"wrote {out} ({total} entries)")
    # For the website's Airlines tab: which airlines FlightScout searches
    # directly, and whether that works everywhere or only with a local runner.
    direct: dict[str, str] = {}
    for name, codes in s.AIRLINE_CODES.items():
        if name in s.HEADFUL_ONLY:
            continue
        where = "local" if name in s.BROWSER_SOURCES else "everywhere"
        for c in codes:
            if direct.get(c) != "everywhere":
                direct[c] = where
    web = Path(__file__).resolve().parents[2] / "web" / "src" / "lib" / "direct-airlines.json"
    web.write_text(json.dumps(dict(sorted(direct.items())), indent=0) + "\n")
    print(f"wrote {web} ({len(direct)} airlines)")


if __name__ == "__main__":
    main()
