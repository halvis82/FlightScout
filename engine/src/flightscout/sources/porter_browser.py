"""Porter Airlines (PD) direct from flyporter.com through the shared real Chrome
(see _browser.py). flyporter.com sits behind Cloudflare, which turns plain
HTTP clients away, but headless Chrome gets through.

Flow: load the home page once per session (Cloudflare), then open the search
redirect the booking widget itself uses (/api/redirect-search-flights?...),
which starts a booking session, and make the select flight page's own two
calls from inside the page (BuildFlightSearch, then the Navitaire
availability JSON /flight/GetFlightAvailability). One response covers both
directions of a round trip. ``TotalAmount`` of the cheapest fare
(PorterClassic Basic when offered) is the per passenger price in CAD incl.
taxes and fees, what the page shows. About 2 seconds per search once warm (8 cold).

Stations: data/porter_stations.json, the ``isPorterStation`` airports of the
site's own /api/stations list."""

from __future__ import annotations

import json
import logging
from datetime import date
from functools import cache as memo
from pathlib import Path

from .. import airports, cache
from ..models import Itinerary, SearchQuery
from . import _browser
from ._airline import combine

log = logging.getLogger(__name__)
SITE = "https://www.flyporter.com"


@memo
def stations() -> set[str]:
    return set(json.loads((Path(__file__).parents[1] / "data" / "porter_stations.json").read_text()))


def available() -> bool:
    return _browser.available()


def _pairs(origins: list[str], destinations: list[str]) -> list[tuple[str, str]]:
    st = stations()

    def ca(c):
        return (a := airports.get(c)) is not None and a.country == "CA"
    # Porter flies within Canada and between Canada and the US/sun spots, not US domestic
    return [(o, d) for o in origins for d in destinations
            if o in st and d in st and o != d and (ca(o) or ca(d))]


def relevant(origins: list[str], destinations: list[str]) -> bool:
    return bool(_pairs(origins, destinations)) and available()


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1) -> str:
    return (f"{SITE}/api/redirect-search-flights?departStation={origin}&destination={dest}&depDate={dep}"
            + (f"&rtnDate={ret}" if ret else "")
            + f"&paxADT={adults}&paxCHD=0&paxINF=0&trpType={'RoundTrip' if ret else 'OneWay'}"
              f"&fareClass=R&bookWithPoints=0")


def parse(data: dict, adults: int = 1) -> list[list[dict]]:
    """GetFlightAvailability JSON -> one list of journeys per direction."""
    bounds = []
    for res in data.get("searchResults") or []:
        out = []
        for j in res.get("AvailableJourneys") or []:
            fares = [f for f in j.get("Fares") or [] if f.get("TotalAmount") and (f.get("AvailableCount") or 0) > 0]
            if not fares:
                continue
            best = min(fares, key=lambda f: f["TotalAmount"])
            segs = []
            for s in j.get("Segments") or []:
                fd = s["FlightDesignator"]
                legs = s.get("Legs") or [{}]
                segs.append({"origin": s["DepartureStation"], "destination": s["ArrivalStation"],
                             "departure": s["formattedSTD"], "arrival": s["formattedSTA"],
                             "carrier": fd["CarrierCode"].strip(), "number": fd["FlightNumber"].strip(),
                             "aircraft": (legs[0].get("LegInfo") or {}).get("EquipmentType")})
            if not segs:
                continue
            dur = j.get("Duration") or {}
            out.append({"segments": segs, "total": round(float(best["TotalAmount"]) * adults, 2),
                        "fare": best.get("ProductClass"), "seats": best.get("AvailableCount"),
                        "duration": int(dur["TotalMinutes"]) if dur.get("TotalMinutes") else None})
        bounds.append(out)
    return bounds


_JS = """async ([build, dates]) => {
  const h = {'X-Requested-With': 'XMLHttpRequest'};
  const b = await fetch('/en-ca/flight/BuildFlightSearch', {method: 'POST', body: build,
    headers: {...h, 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'}});
  const crit = (await b.json()).FlightSearchCriteria[0];
  crit.forEach((c, i) => { c.BeginDate = c.EndDate = dates[i]; });
  const r = await fetch('/en-ca/flight/GetFlightAvailability', {method: 'POST', body: JSON.stringify(crit),
    headers: {...h, 'Content-Type': 'application/json; charset=UTF-8', 'Accept': 'application/json'}});
  if (!r.ok) throw new Error('GetFlightAvailability ' + r.status);
  return await r.text();
}"""


def _fetch(origin: str, dest: str, dep: date, ret: date | None, adults: int) -> dict:
    """Open the search redirect just far enough for the server to start a
    booking session with this search (the select page itself loads slowly,
    about 20 s), then make the page's own two calls: BuildFlightSearch gives
    the Navitaire criteria, GetFlightAvailability the flights."""
    url = deeplink(origin, dest, dep, ret, adults)
    build = (f"DepartStation={origin}&ArrivalStation={dest}&FlightType={1 if ret else 0}&GetByDirection=3"
             f"&DepartDate={dep:%Y%%2F%m%%2F%d}&ReturnDate={f'{ret:%Y%%2F%m%%2F%d}' if ret else 'Invalid+date'}"
             f"&TripType=&LoyaltyFilter=0")
    dates = [str(dep)] + ([str(ret)] if ret else [])

    def job(page) -> str:
        if "flyporter.com" not in page.url:  # new session: pass Cloudflare on the home page first
            try:
                page.goto(SITE + "/en-ca/", wait_until="domcontentloaded", timeout=45000)
            except Exception as e:  # the Next.js app sometimes aborts the first load with a redirect
                log.debug("porter home: %s", e)
            page.wait_for_timeout(2500)
            _browser.pass_cloudflare(page, 30)
        page.goto(url, wait_until="commit", timeout=45000)
        page.evaluate("window.stop()")
        return page.evaluate(_JS, [build, dates])

    txt = _browser.run(job, "porter", timeout=100)
    if not txt:
        raise RuntimeError("porter: no availability response (Cloudflare or site change)")
    return json.loads(txt)


def search(q: SearchQuery) -> list[Itinerary]:
    pairs = _pairs(q.origins, q.destinations)
    if not pairs or not available() or q.cabin not in ("economy", "premium"):
        return []
    out: list[Itinerary] = []
    for o, d in pairs[:2]:
        url = deeplink(o, d, q.departure, q.return_date, q.adults)
        key = f"porter:{o}:{d}:{q.departure}:{q.return_date}:{q.adults}"
        if (data := cache.get(key)) is None:
            data = _fetch(o, d, q.departure, q.return_date, q.adults)
            cache.put(key, data)
        bounds = parse(data, q.adults)
        if not bounds or (q.return_date and len(bounds) < 2):
            continue
        out += combine(q, "porter", "Porter Airlines", bounds[0], bounds[1] if q.return_date else None, "CAD",
                       url, {"PD": "Porter Airlines"},
                       note="Porter cheapest fare (usually PorterClassic Basic) incl. taxes; bags extra.")
    return out
