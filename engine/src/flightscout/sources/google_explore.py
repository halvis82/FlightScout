"""Google Flights Explore ("anywhere") through a real headless browser.
Google gates the GetExploreDestinations endpoint behind a header only its
page script can produce, so we load the Explore page and read that response.
Needs Playwright + Chrome, so it runs in the local runner, the CLI and the
GitHub Actions tracker (which warms a shared cache), not on Vercel."""

from __future__ import annotations

import json
import logging
from datetime import date

from .. import airports, cache
from ..models import Destination

log = logging.getLogger(__name__)
SOCS = "CAESEwgDEgk0ODE3Nzk3MjQaAmVuIAEaBgiA_LyaBg"


def available() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


def _chunks(body: str):
    for line in body.split("\n"):
        if not line.startswith("[["):
            continue
        try:
            for chunk in json.loads(line):
                if chunk and chunk[0] == "wrb.fr" and chunk[2]:
                    yield json.loads(chunk[2])
        except (ValueError, TypeError, IndexError):
            continue


def parse(bodies: list[str], origin: str, currency: str) -> list[Destination]:
    places: dict[str, dict] = {}
    prices: dict[str, dict] = {}
    for body in bodies:
        for inner in _chunks(body):
            # destination descriptors: [mid, [lat, lon], city, img, country, ..., dep(11), ret(12)]
            try:
                for d in inner[3][0]:
                    places[d[0]] = {"lat": d[1][0], "lon": d[1][1], "city": d[2], "country": d[4],
                                    "dep": d[11], "ret": d[12]}
            except (IndexError, TypeError):
                pass
            # prices: [mid, [[null, price], token], ..., [carrier, name, stops, minutes, null, IATA, ...]]
            try:
                for p in inner[4][0]:
                    price = p[1][0][1]
                    info = p[6] or []
                    if price is None:
                        continue
                    prices[p[0]] = {"price": float(price), "carrier": info[1] if len(info) > 1 else None,
                                    "stops": info[2] if len(info) > 2 else None,
                                    "minutes": info[3] if len(info) > 3 else None,
                                    "iata": info[5] if len(info) > 5 else None}
            except (IndexError, TypeError):
                pass
    out = []
    for mid, pr in prices.items():
        pl = places.get(mid, {})
        iata = pr.get("iata")
        ap = airports.get(iata) if iata else None
        dep = date.fromisoformat(pl["dep"]) if pl.get("dep") else None
        ret = date.fromisoformat(pl["ret"]) if pl.get("ret") else None
        q = f"Flights from {origin} to {iata or pl.get('city', '')}" + (f" on {dep} through {ret}" if dep and ret else "")
        out.append(Destination(
            origin=origin, destination=iata or mid, city=pl.get("city") or (ap.city if ap else None),
            country=(ap.country if ap else None), price=pr["price"], currency=currency, departure=dep,
            return_date=ret, source="google",
            booking_url="https://www.google.com/travel/flights?q=" + q.replace(" ", "%20") + f"&curr={currency}",
            lat=pl.get("lat") or (ap.lat if ap else None), lon=pl.get("lon") or (ap.lon if ap else None),
        ))
    return out


def explore(origin: str, currency: str = "USD", month: str | None = None, zoom_out: int = 3) -> list[Destination]:
    """Cheapest week long round trips from ``origin`` to everywhere, over the
    next months (Google's default), or in ``month`` (e.g. "November")."""
    key = f"gexplore:{origin}:{currency}:{month}"
    if (hit := cache.get(key, ttl=6 * 3600)) is not None:
        return [Destination(**x) for x in hit]
    from playwright.sync_api import sync_playwright

    q = f"flights from {origin}" + (f" in {month}" if month else "")
    url = f"https://www.google.com/travel/explore?q={q.replace(' ', '%20')}&curr={currency}&hl=en&gl=US"
    bodies: list[str] = []
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(channel="chrome", headless=True)
        except Exception:
            browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(locale="en-US")
        ctx.add_cookies([{"name": "SOCS", "value": SOCS, "domain": ".google.com", "path": "/"}])
        page = ctx.new_page()

        def on(r):
            if "GetExploreDestinations" in r.url:
                try:
                    bodies.append(r.text())
                except Exception:
                    pass

        page.on("response", on)
        page.goto(url, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(2000)
        # Explore only loads destinations inside the visible map, so zoom out
        # to fetch the rest of the world (each zoom triggers another request).
        vp = page.viewport_size or {"width": 1280, "height": 720}
        page.mouse.move(vp["width"] * 0.7, vp["height"] * 0.55)  # over the map
        for _ in range(zoom_out):
            n = len(bodies)
            page.mouse.wheel(0, 600)
            for _ in range(10):
                page.wait_for_timeout(400)
                if len(bodies) > n:
                    break
        page.wait_for_timeout(1500)
        browser.close()
    out = parse(bodies, origin, currency)
    cache.put(key, [d.model_dump(mode="json") for d in out])
    return out
