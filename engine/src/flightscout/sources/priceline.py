"""Priceline (US OTA) flight search results, keyless.

priceline.com/m/fly/search/... is server rendered: the HTML carries the
page's Redux state (``window.__PRELOADED_STATE__``) with the first page of
listings, cheapest first (25 itineraries, plus a few "recommended" ones),
each with its fare brands and the total price for all passengers incl. taxes
and fees. One plain HTTP GET with Chrome TLS impersonation, 10 to 25 seconds
(the server runs the live search before it answers). When PerimeterX blocks
the plain request and a browser is available, the same page is loaded in
the shared headless Chrome (sources/_browser.py) and parsed the same way.

Priceline adds nearby airports (ONT for LAX, say); we keep only the airports
that were asked for. Round trips: the page lists outbound flights with the
cheapest round trip total and the return is picked on the next page, so
those come back as ``return_pending`` (like Google's round trip rows).
Prices are USD (priceline.com is US only)."""

from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

from curl_cffi import requests as cr

from .. import cache
from ..models import Itinerary, SearchQuery, Segment, Slice
from . import _browser

log = logging.getLogger(__name__)
SITE = "https://www.priceline.com"
_CABIN = {"economy": "ECO", "premium": "PEC", "business": "BUS", "first": "FST"}
_MARK = "window.__PRELOADED_STATE__ = "
_local = threading.local()


def available() -> bool:
    return True  # plain HTTP; the browser is only a fallback


def relevant(origins: list[str], destinations: list[str]) -> bool:
    return True  # sells every market, prices in USD


def _session() -> cr.Session:
    if not hasattr(_local, "s"):
        _local.s = cr.Session(impersonate="chrome")
    return _local.s


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1,
             cabin: str = "economy") -> str:
    path = f"/{origin}-{dest}-{dep:%Y%m%d}/"
    if ret:
        path += f"{dest}-{origin}-{ret:%Y%m%d}/"
    return f"{SITE}/m/fly/search{path}?cabin-class={_CABIN.get(cabin, 'ECO')}&num-adults={adults}"


def state_from_html(html: str) -> dict | None:
    i = html.find(_MARK)
    if i < 0:
        return None
    try:
        return json.JSONDecoder().raw_decode(html[i + len(_MARK):])[0]
    except ValueError:
        return None


def _price(prices: list[dict], kind: str = "TOTAL_PRICE") -> tuple[float, str] | None:
    for p in prices or []:
        if p.get("type") == kind and p.get("amount") is not None:
            return float(p["amount"]), p.get("currencyCode") or "USD"
    return None


def _slice(sl: dict) -> Slice:
    segs = []
    for s in sl["segments"]:
        segs.append(Segment(
            origin=s["departInfo"]["airport"]["code"], destination=s["arrivalInfo"]["airport"]["code"],
            departure=datetime.fromisoformat(s["departInfo"]["time"]["dateTime"][:19]),
            arrival=datetime.fromisoformat(s["arrivalInfo"]["time"]["dateTime"][:19]),
            carrier=s["marketingAirline"], flight_number=str(s.get("flightNumber") or "") or None,
            duration_min=s.get("duration"), aircraft=s.get("equipment") or None,
        ))
    dur = sl.get("durationInMinutes")
    if not dur:
        dur = int((segs[-1].arrival - segs[0].departure).total_seconds() // 60)
    return Slice(segments=segs, duration_min=max(int(dur), 1))


def _baggage(fare: dict | None) -> dict | None:
    if not fare:
        return None
    anc = {a.get("tag"): a.get("offerType") for a in fare.get("ancillaries") or []}
    if "CARRY_ON" not in anc and "CHECKED_BAG" not in anc:
        return None
    # offerType: C = included, F = for a fee, N = not offered
    return {"hand": 1 if anc.get("CARRY_ON") == "C" else 0, "checked": 1 if anc.get("CHECKED_BAG") == "C" else 0}


def parse(state: dict, origins: list[str] | None = None, destinations: list[str] | None = None,
          round_trip: bool = False, url: str = SITE, max_stops: int | None = None) -> list[Itinerary]:
    """Priceline page state -> Itineraries (one per listing, its cheapest
    fare brand). ``origins``/``destinations`` drop the nearby airports
    Priceline mixes in."""
    rows = list(((state.get("listings") or {}).get("response")) or [])
    for group in (state.get("recommendedListings") or {}).values():
        rows += group or []
    names = {a.get("code"): a.get("name") for l in rows for a in l.get("airlines") or []}
    out, seen = [], set()
    for l in rows:
        if l.get("id") in seen or not l.get("slices"):
            continue
        seen.add(l.get("id"))
        pr = _price(l.get("price"))
        if not pr:
            continue
        try:
            slices = [_slice(sl) for sl in l["slices"]]
        except (KeyError, TypeError, ValueError) as e:
            log.debug("priceline: bad listing %s: %s", l.get("id"), e)
            continue
        if origins and slices[0].origin not in origins:
            continue
        if destinations and slices[0].destination not in destinations:
            continue
        if max_stops is not None and any(s.stops > max_stops for s in slices):
            continue
        for s in slices:
            for seg in s.segments:
                seg.carrier_name = names.get(seg.carrier)
        fare = next((f for f in l.get("fareBrands") or [] if f.get("isSelected")), None) or \
            next(iter(l.get("fareBrands") or []), None)
        warn = ["Sold by Priceline (online travel agency), not the airline."]
        if fare and fare.get("name"):
            warn.append(f"Priceline cheapest fare brand: {fare['name']}.")
        pending = round_trip and len(slices) == 1
        if pending:
            warn.append("Round trip price from Priceline; pick the return flight on Priceline.")
        if l.get("isFused"):
            warn.append("Priceline combines separate tickets on this itinerary.")
        seats = l.get("seatsAvailable")
        if seats and seats <= 3:
            warn.append("Only a few seats left at this Priceline fare.")
        out.append(Itinerary(
            source="priceline", price=round(pr[0], 2), currency=pr[1], slices=slices, booking_url=url,
            seller="Priceline", seller_kind="ota", self_transfer=bool(l.get("isFused")),
            return_pending=pending, baggage=_baggage(fare), warnings=warn,
        ))
    return out


def _fetch_browser(url: str) -> dict | None:
    def job(page):
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        for _ in range(60):
            html = page.content()
            if _MARK in html:
                return html
            page.wait_for_timeout(500)
        return ""
    return state_from_html(_browser.run(job, "priceline", timeout=120) or "")


def _fetch(url: str) -> dict:
    key = f"priceline:{url}"
    if (hit := cache.get(key, ttl=1800)) is not None:
        return hit
    r = _session().get(url, timeout=60, headers={"Accept": "text/html", "Referer": SITE + "/"})
    st = state_from_html(r.text) if r.status_code == 200 else None
    if st is None and _browser.available():
        log.info("priceline: plain HTTP got %s without results, trying the browser", r.status_code)
        st = _fetch_browser(url)
    if st is None:
        raise RuntimeError(f"priceline: no results page (HTTP {r.status_code})")
    if st.get("listingsHasErrored"):
        raise RuntimeError("priceline: the site reported a search error")
    # keep only what parse() reads: the page state also holds session data
    slim = {"listings": {"response": (st.get("listings") or {}).get("response") or []},
            "recommendedListings": st.get("recommendedListings") or {}}
    cache.put(key, slim)
    return slim


def search(q: SearchQuery) -> list[Itinerary]:
    pairs = [(o, d) for o in q.origins[:2] for d in q.destinations[:2] if o != d]

    def one(pair):
        o, d = pair
        url = deeplink(o, d, q.departure, q.return_date, q.adults, q.cabin)
        return parse(_fetch(url), [o], [d], bool(q.return_date), url, q.max_stops)

    out: list[Itinerary] = []
    errors = []
    with ThreadPoolExecutor(max_workers=2) as ex:
        for pair, fut in [(p, ex.submit(one, p)) for p in pairs]:
            try:
                out += fut.result()
            except Exception as e:  # one airport pair failing keeps the others
                log.warning("priceline %s-%s failed: %s", *pair, e)
                errors.append(e)
    if errors and len(errors) == len(pairs):
        raise errors[0]
    return out
