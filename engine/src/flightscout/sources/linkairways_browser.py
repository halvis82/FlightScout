"""Link Airways (FC, Australia) direct from its booking engine
(search.linkairways.com) through the shared headless Chrome (see _browser.py).
Regional airline out of Brisbane, Canberra, Dubbo and Melbourne that Google
and Kiwi barely carry.

The results page is a plain GET (``/FC/Flight.aspx?depCity=..&arrCity=..``)
but it bounces through two JavaScript redirects that set the session, so
plain HTTP loops; headless Chrome follows them in a few seconds. One page load
per search, round trips included (both directions on one page), about 10 to
17 seconds. We read the rendered flight rows (times, flight number, one price
per fare family) straight from the DOM.

Prices: each fare family cell is the per adult total incl. taxes ("Note:
Total Price shown - no card payment fees apply"; the cell tooltip is Base Fare
+ Tax = Total). Verified September 2026 (headless): BNE-ARM 22 Oct 2026 FC883
"AUD 315.00" Deal (258.56 + 56.44 tax); for 2 adults the booking summary says
"Total Price AUD 630.00", which is what we return. Round trips add the
cheapest family of each direction, like the booking summary. Nonstop flights
only (the few connections come without airport codes)."""

from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime

from .. import cache
from ..models import Itinerary, SearchQuery
from . import _browser
from ._airline import combine

log = logging.getLogger(__name__)
SITE = "https://search.linkairways.com"
NAMES = {"FC": "Link Airways"}
CURRENCY = "AUD"
# Link Airways stations (booking engine origin list, September 2026).
STATIONS = {"ARM", "ZBL", "BNE", "BDB", "CBR", "CFS", "DBO", "HBA", "IVR", "LST", "MEL", "NAA", "NTL", "OAG",
            "TMW"}
FAMILIES = ["Deal", "Standard", "Freedom", "Flexible"]
_JS = r"""() => { const out = {};
 for (const dir of ['OB', 'IB']) { const root = document.querySelector('#div' + dir + 'FlightResults'); if (!root) continue;
  out[dir] = [...root.querySelectorAll('.list-item.item')].filter(it => it.querySelector('ul.city-list')).map(it => {
   const lis = it.querySelectorAll(':scope > div > ul.city-list > li');
   const txt = e => e ? e.innerText.replace(/\s+/g, ' ').trim() : null;
   return {dep: txt(lis[0]), arr: txt(lis[1]), stops: txt(it.querySelector('.fdetails-popover li span')),
           aircraft: txt(it.querySelector('.flight-popover .aircraftname')),
           fares: [...it.querySelectorAll('label.ffare')].map(txt)}; }); }
 return out; }"""


def available() -> bool:
    return _browser.available()


def relevant(origins: list[str], destinations: list[str]) -> bool:
    if not available():
        return False
    return any(o in STATIONS for o in origins) and any(d in STATIONS for d in destinations)


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1) -> str:
    return (f"{SITE}/FC/Flight.aspx?aid=268&culture=en-GB&st=fa&sid=&Jtype={2 if ret else 1}"
            f"&depCity={origin}&arrCity={dest}&depDate={dep:%d/%m/%Y}&arrDate={(ret or dep):%d/%m/%Y}"
            f"&adult1={adults}&child1=0&infant1=0&promotioncode=")


_ROW = re.compile(r"(\d{1,2}:\d{2}) \w{3}, (\d{1,2} \w{3} \d{4}) .*?\b(FC) (\d+)")
_ARR = re.compile(r"(\d{1,2}:\d{2}) \w{3}, (\d{1,2} \w{3} \d{4})")
_DUR = re.compile(r"(\d+)h (\d+)min")


def _iso(hm: str, d: str) -> str:
    return datetime.strptime(f"{d} {hm}", "%d %b %Y %H:%M").isoformat()


def parse(rows: list[dict], origin: str, dest: str, adults: int = 1) -> list[dict]:
    """Rendered flight rows of one direction -> nonstop journeys at the
    cheapest fare family, for ``adults`` adults."""
    out = []
    for r in rows or []:
        if "direct" not in (r.get("stops") or "").lower():
            continue
        m, a = _ROW.search(r.get("dep") or ""), _ARR.search(r.get("arr") or "")
        prices = []
        for i, f in enumerate(r.get("fares") or []):
            p = re.search(r"AUD\s*([\d,]+\.?\d*)", f or "")
            if p:
                prices.append((float(p.group(1).replace(",", "")), FAMILIES[i] if i < len(FAMILIES) else None))
        if not m or not a or not prices:
            continue
        price, fam = min(prices)
        dm = _DUR.search(r.get("arr") or "")
        dur = int(dm.group(1)) * 60 + int(dm.group(2)) if dm else None
        out.append({"segments": [{"origin": origin, "destination": dest, "departure": _iso(m.group(1), m.group(2)),
                                  "arrival": _iso(a.group(1), a.group(2)), "carrier": m.group(3),
                                  "number": m.group(4), "duration": dur, "aircraft": r.get("aircraft")}],
                    "total": round(price * adults, 2), "fare": fam, "duration": dur, "seats": None})
    return out


def _fetch(o: str, d: str, dep: date, ret: date | None, adults: int) -> dict:
    key = f"linkairways:{o}:{d}:{dep}:{ret}:{adults}"
    if (hit := cache.get(key)) is not None:
        return hit
    url = deeplink(o, d, dep, ret, adults)

    def job(page) -> dict:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        end = time.time() + 40
        while time.time() < end:
            if "Flight.aspx" in page.url and page.query_selector("#divOBFlightResults"):
                break
            page.wait_for_timeout(400)
        else:
            raise RuntimeError(f"linkairways: no results page ({page.url[:80]})")
        page.wait_for_timeout(800)
        return page.evaluate(_JS)

    data = _browser.run(job, "linkairways", timeout=90)
    cache.put(key, data)
    return data


def search(q: SearchQuery) -> list[Itinerary]:
    if q.cabin != "economy" or not relevant(q.origins, q.destinations):
        return []
    out: list[Itinerary] = []
    pairs = [(o, d) for o in q.origins if o in STATIONS for d in q.destinations if d in STATIONS and d != o][:2]
    for o, d in pairs:
        data = _fetch(o, d, q.departure, q.return_date, q.adults)
        outs = parse(data.get("OB"), o, d, q.adults)
        backs = parse(data.get("IB"), d, o, q.adults) if q.return_date else None
        if not outs or (q.return_date and not backs):
            continue
        out += combine(q, "linkairways", "Link Airways", outs, backs, CURRENCY,
                       deeplink(o, d, q.departure, q.return_date, q.adults), NAMES,
                       note="Link Airways cheapest fare family incl. taxes (usually Deal).")
    return out
