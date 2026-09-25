"""Caribbean Airlines (BW) direct from caribbean-airlines.com through the
shared real Chrome (see _browser.py). The site hands searches to Amadeus
e-Retail (book.bw.amadeus.com/plnext/CaribbeanAirlines), which sits behind
Imperva: plain HTTP clients get "Pardon Our Interruption", headless Chrome
gets through.

Flow, exactly the site's own: on caribbean-airlines.com, POST the search to
/api/Booking/GetBookingParams (it returns the encrypted Amadeus form), submit
that form, and read the availability JSON that the Amadeus select page embeds
(``PlnextPageProvider.init({config: ...})`` ->
pageData.business.Availability). ``recommendationList`` holds the fares
(``recoAmount.totalAmount`` for all passengers incl. taxes and fees) per
fare family, pointing at flights of ``proposedBounds``; a round trip must
take both halves from the same recommendation. Prices are in USD. About 8
seconds per search warm (the Amadeus page is heavy).

Routes: data/caribbean_routes.json, the site's own /api/Flight/Getroutesflights
(own metal, interline markets dropped)."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from functools import cache as memo
from pathlib import Path

from .. import cache
from ..models import Itinerary, SearchQuery
from . import _browser
from ._airline import combine

log = logging.getLogger(__name__)
SITE = "https://www.caribbean-airlines.com"

_JS = """async ([o, d, dep, ret, adults]) => {
  const fd = new FormData();
  fd.append('pax', JSON.stringify({pax_list: [], adultcount: adults, youngadultcount: 0, seniorcount: 0,
                                    childcount: 0, infantcount: 0, sinfantcount: 0}));
  const f = {btype: 'R', mobile: 'false', from: o, to: d, dep: dep, arr: ret || dep, ttype: ret ? 'R' : 'O',
             interline: 'false', promocode: ''};
  for (const [k, v] of Object.entries(f)) fd.append(k, v);
  const r = await fetch('/api/Booking/GetBookingParams', {method: 'POST', body: fd});
  const data = await r.json();
  if (!data || !data.status) throw new Error('GetBookingParams: ' + JSON.stringify(data).slice(0, 200));
  const form = document.createElement('form');
  form.method = 'POST'; form.action = data.url;
  data.params.split('&').forEach(kv => {
    const i = kv.indexOf('='), inp = document.createElement('input');
    inp.type = 'hidden'; inp.name = kv.slice(0, i); inp.value = kv.slice(i + 1); form.appendChild(inp);
  });
  document.body.appendChild(form); form.submit();
  return data.url;
}"""


@memo
def routes() -> dict[str, set[str]]:
    raw = json.loads((Path(__file__).parents[1] / "data" / "caribbean_routes.json").read_text())
    return {o: set(ds) for o, ds in raw.items()}


def available() -> bool:
    return _browser.available()


def _pairs(origins: list[str], destinations: list[str]) -> list[tuple[str, str]]:
    r = routes()
    return [(o, d) for o in origins for d in destinations if d in r.get(o, ())]


def relevant(origins: list[str], destinations: list[str]) -> bool:
    return bool(_pairs(origins, destinations)) and available()


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1) -> str:
    # The search is a POST with an encrypted form, there is no search URL.
    return SITE + "/"


def _dt(s: str) -> str:
    return datetime.strptime(s.replace(" ", " "), "%b %d, %Y, %I:%M:%S %p").isoformat()


def availability(html: str) -> dict:
    """The select page's embedded config -> its Availability block."""
    i = html.index("config : ") + len("config : ")
    cfg, _ = json.JSONDecoder().raw_decode(html[i:])
    return cfg["pageDefinitionConfig"]["pageData"]["business"]["Availability"]


def parse(av: dict) -> tuple[list[dict], list[list[tuple[int, int, float]]]]:
    """Availability -> (flights by id per bound, [(out id, back id or -1, total)])."""
    bounds = []
    for b in av.get("proposedBounds") or []:
        fl = {}
        for g in b.get("proposedFlightsGroup") or []:
            segs = [{"origin": s["beginLocation"]["locationCode"], "destination": s["endLocation"]["locationCode"],
                     "departure": _dt(s["beginDate"]), "arrival": _dt(s["endDate"]),
                     "carrier": (s.get("airline") or {}).get("code") or "BW", "number": s["flightNumber"],
                     "aircraft": (s.get("equipment") or {}).get("name"),
                     "duration": int(s["flightTime"] // 60000) if s.get("flightTime") else None} for s in g["segments"]]
            first, last = g["segments"][0], g["segments"][-1]
            dur = (datetime.strptime(last["endDateGMT"].replace(" ", " "), "%b %d, %Y, %I:%M:%S %p")
                   - datetime.strptime(first["beginDateGMT"].replace(" ", " "), "%b %d, %Y, %I:%M:%S %p"))
            fl[g["proposedBoundId"]] = {"segments": segs, "duration": int(dur.total_seconds() // 60)}
        bounds.append(fl)
    prices: dict[tuple[int, int], float] = {}
    for r in av.get("recommendationList") or []:
        total = (r.get("recoAmount") or {}).get("totalAmount")
        bs = r.get("bounds") or []
        if not total or not bs:
            continue
        outs = [f["flightId"] for f in bs[0].get("flightGroupList") or []]
        backs = [f["flightId"] for f in bs[1].get("flightGroupList") or []] if len(bs) > 1 else [-1]
        for a in outs:
            for b in backs:
                if (a, b) not in prices or total < prices[(a, b)]:
                    prices[(a, b)] = float(total)
    return bounds, [(a, b, p) for (a, b), p in prices.items()]


def _fetch(o: str, d: str, dep: date, ret: date | None, adults: int) -> dict:
    def attempt(page) -> str:
        page.goto(SITE + "/", wait_until="domcontentloaded", timeout=30000)
        with page.expect_navigation(url=lambda u: "amadeus.com" in u, wait_until="domcontentloaded", timeout=45000):
            page.evaluate(_JS, [o, d, dep.strftime("%Y%m%d"), ret.strftime("%Y%m%d") if ret else "", adults])
        html = ""
        for _ in range(60):  # the Override page may bounce once before the select page
            try:
                html = page.content()
            except Exception:  # still navigating
                html = ""
            if "config : " in html and "proposedBounds" in html:
                return html
            page.wait_for_timeout(500)
        return html

    def job(page) -> str:
        try:
            html = attempt(page)
        except Exception as e:  # a slow Amadeus redirect: try once more
            log.info("caribbean: retry after %s", str(e)[:120])
            html = ""
        if "config : " not in html:
            html = attempt(page)
        return html

    html = _browser.run(job, "caribbean", timeout=200)
    if "config : " not in html:
        if "Pardon Our Interruption" in html:
            raise RuntimeError("caribbean: blocked by the bot check")
        return {}
    return availability(html)


def search(q: SearchQuery) -> list[Itinerary]:
    pairs = _pairs(q.origins, q.destinations)
    if not pairs or not available() or q.cabin != "economy":
        return []
    out: list[Itinerary] = []
    for o, d in pairs[:2]:
        key = f"caribbean:{o}:{d}:{q.departure}:{q.return_date}:{q.adults}"
        if (av := cache.get(key)) is None:
            av = _fetch(o, d, q.departure, q.return_date, q.adults)
            cache.put(key, av)
        bounds, prices = parse(av)
        if not bounds or (q.return_date and len(bounds) < 2):
            continue
        names = {"BW": "Caribbean Airlines"}
        pick = sorted(prices, key=lambda x: x[2])
        seen = set()
        for a, b, total in pick:
            if (a, b) in seen or a not in bounds[0] or (b != -1 and (len(bounds) < 2 or b not in bounds[1])):
                continue
            seen.add((a, b))
            ja = bounds[0][a]
            jb = bounds[1][b] if b != -1 else None
            if q.max_stops is not None and any(j and len(j["segments"]) - 1 > q.max_stops for j in (ja, jb)):
                continue
            its = combine(q, "caribbean", "Caribbean Airlines", [{**ja, "total": total}],
                          [{**jb, "total": 0}] if jb else None, "USD", deeplink(o, d, q.departure, q.return_date),
                          names, note="Caribbean Airlines cheapest fare incl. taxes. Search the same flights on "
                                      "caribbean-airlines.com (no search links).")
            out += its
            if len(seen) >= (36 if q.return_date else 8):
                break
    return out
