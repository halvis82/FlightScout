"""Jet2.com (LS) direct from jet2.com. Jet2 sells only on its own site (no
GDS), so Google and Kiwi often miss its fares or show stale ones.

No key and no browser: the flight selection page
(/en/search-results/<destination>?dep=..&arr=..) is a server render with the
whole priced result embedded as ``searchInitialResponseJson`` (every outbound
x inbound combination for the chosen date, with the per direction price for
all passengers incl. taxes, and the "selected" cheapest flight with its flight
number). Plain Chrome TLS (curl_cffi) is enough for that page. The one JSON
call we make (/api/search-results/low-fare-search/, same origin) only tells
us the destination's URL slug, and Akamai lets it through after a home page
visit in the same session.

Jet2 sells from its 14 UK bases; one ways from abroad back to the UK are not
offered by this path, so only UK-origin searches are served. Prices are in GBP
for all adults; each direction is priced on its own (the site adds them), so
round trips are outbound x inbound. Only the cheapest flight of each direction
comes with its flight number."""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import date, datetime

from curl_cffi import requests as cr

from .. import cache
from ..models import Itinerary, SearchQuery, Segment, Slice
from ._airline import countries

SITE = "https://www.jet2.com"
# Jet2's UK bases (the site's own "allUKAirports" list, September 2026).
UK_BASES = {"BFS", "BHX", "BOH", "BRS", "EDI", "EMA", "GLA", "LBA", "LGW", "LPL", "LTN", "MAN", "NCL", "STN"}
# Countries of Jet2 destinations (allairportinformation, September 2026).
COUNTRIES = {"AT", "BG", "CH", "CY", "CZ", "DE", "DK", "EE", "EG", "ES", "FR", "GR", "HR", "HU", "IS", "IT", "JE",
             "MA", "ME", "MT", "NO", "PL", "PT", "TN", "TR"}
_DATA = re.compile(r"var searchInitialResponseJson = '(.*?)';\s", re.S)
_lock = threading.Lock()
_session: cr.Session | None = None
_last = 0.0
_MIN_GAP = 1.0
_MAX_PAGES = 3  # combinations come 6 per page, cheapest first


def _sess() -> cr.Session:
    global _session
    with _lock:
        if _session is None:
            _session = cr.Session(impersonate="chrome")
            try:  # Akamai cookies for the JSON call
                _session.get(f"{SITE}/", timeout=30)
            except Exception:
                pass
        return _session


def _get(url: str, **kw):
    global _last
    with _lock:
        wait = _MIN_GAP - (time.time() - _last)
        if wait > 0:
            time.sleep(wait)
        _last = time.time()
    r = _sess().get(url, timeout=45, **kw)
    r.raise_for_status()
    return r


def relevant(origins: list[str], destinations: list[str]) -> bool:
    return any(o in UK_BASES for o in origins) and bool(countries(destinations) & COUNTRIES)


def _query(o: str, d: str, dep: date, ret: date | None, adults: int) -> str:
    dur = (ret - dep).days if ret else 7  # one way still wants a duration
    return (f"dep={o}&arr={d}&from={dep.isoformat()}&selectedDate={dep:%d-%m-%Y}&adults={adults}&infants=0"
            f"&duration={dur}&oneway={'false' if ret else 'true'}")


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1,
             slug: str | None = None) -> str:
    if slug:
        return f"{SITE}/en/search-results/{slug}?{_query(origin, dest, dep, ret, adults)}"
    return f"{SITE}/search-results?{_query(origin, dest, dep, ret, adults)}"


def _slug(o: str, d: str, dep: date) -> str | None:
    """The destination's URL segment (e.g. "alicante"), from the site's own
    destination search. None when Jet2 does not fly o -> d."""
    key = f"jet2:slug:{o}:{d}"
    if (hit := cache.get(key, ttl=7 * 86400)) is not None:
        return hit or None
    r = _get(f"{SITE}/api/search-results/low-fare-search/?{_query(o, d, dep, None, 1)}",
             headers={"Accept": "application/json, text/plain, */*", "Referer": f"{SITE}/"})
    data = r.json()
    data = data.get("data", data)
    slug = next((x.get("urlSegment") for x in data.get("destinations") or [] if x.get("airportCode") == d), None)
    if slug is None and not (data.get("airportAvailabilities") or {}):
        return None  # unknown answer: don't cache a negative
    cache.put(key, slug or "")
    return slug


def page_data(html: str) -> dict:
    m = _DATA.search(html)
    if not m:
        raise RuntimeError("jet2: no search data on the flight page")
    return json.loads(m.group(1).replace('\\"', '"').replace("\\'", "'"))


def _hm(s: str | None) -> int | None:
    if not s:
        return None
    h, m, *_ = s.split(":")
    return int(h) * 60 + int(m)


def parse(data: dict, dep: date, ret: date | None = None) -> tuple[list[dict], list[dict], str]:
    """Flight page data -> (outbound journeys, inbound journeys, currency).
    Each journey: {"id", "origin", "destination", "departure", "arrival",
    "number" (only for the cheapest), "duration", "total"} with total the
    price for all passengers."""
    if data.get("isError"):
        return [], [], "GBP"
    sel = {f["flightId"]: f.get("flightNumber") for f in (data.get("selectedOutboundFlight"),
                                                          data.get("selectedInboundFlight")) if f and f.get("flightId")}
    cur = (data.get("selectedOutboundFlight") or {}).get("currencyCode") or "GBP"
    outs: dict[int, dict] = {}
    backs: dict[int, dict] = {}
    for day in (data.get("trips") or {}).values():
        for t in day:
            ids = t.get("flightIds") or {}
            if t["outboundDepartureTime"][:10] == dep.isoformat() and ids.get("outbound"):
                outs.setdefault(ids["outbound"], {
                    "id": ids["outbound"], "origin": t["outboundDepartureAirportCode"],
                    "destination": t["outboundArrivalAirportCode"], "departure": t["outboundDepartureTime"],
                    "arrival": t["outboundArrivalTime"], "number": sel.get(ids["outbound"]),
                    "duration": _hm(t.get("outboundDuration")), "total": t["outboundPrice"]["total"]})
            if ret and ids.get("inbound") and (t.get("inboundDepartureTime") or "")[:10] == ret.isoformat():
                backs.setdefault(ids["inbound"], {
                    "id": ids["inbound"], "origin": t["inboundDepartureAirportCode"],
                    "destination": t["inboundArrivalAirportCode"], "departure": t["inboundDepartureTime"],
                    "arrival": t["inboundArrivalTime"], "number": sel.get(ids["inbound"]),
                    "duration": _hm(t.get("inboundDuration")), "total": t["inboundPrice"]["total"]})
    return list(outs.values()), list(backs.values()), cur


def _fetch(o: str, d: str, dep: date, ret: date | None, adults: int) -> tuple[str | None, list[dict]]:
    """(destination slug, every result page's data), cached."""
    key = f"jet2:{o}:{d}:{dep}:{ret}:{adults}"
    if (hit := cache.get(key)) is not None:
        return hit[0], hit[1]
    slug = _slug(o, d, dep)
    if not slug:
        cache.put(key, [None, []])
        return None, []
    pages = []
    for n in range(1, _MAX_PAGES + 1):
        url = deeplink(o, d, dep, ret, adults, slug) + (f"&currentPage={n}" if n > 1 else "")
        data = page_data(_get(url).text)
        keep = {k: data.get(k) for k in ("isError", "trips", "selectedOutboundFlight", "selectedInboundFlight",
                                         "pagination")}
        pages.append(keep)
        if data.get("isError") or n >= ((data.get("pagination") or {}).get("totalPages") or 1):
            break
    cache.put(key, [slug, pages])
    return slug, pages


def _slice(j: dict) -> Slice:
    dep, arr = datetime.fromisoformat(j["departure"]), datetime.fromisoformat(j["arrival"])
    dur = j.get("duration") or int((arr - dep).total_seconds() // 60)
    return Slice(segments=[Segment(
        origin=j["origin"], destination=j["destination"],
        departure=dep.replace(tzinfo=None), arrival=arr.replace(tzinfo=None),
        carrier="LS", carrier_name="Jet2.com", flight_number=(j["number"] or "")[2:] or None,
        duration_min=dur)], duration_min=max(dur, 1))


def search(q: SearchQuery) -> list[Itinerary]:
    if not relevant(q.origins, q.destinations):
        return []
    out: list[Itinerary] = []
    for o in [c for c in q.origins if c in UK_BASES][:3]:
        for d in [c for c in q.destinations if c not in UK_BASES][:3]:
            slug, pages = _fetch(o, d, q.departure, q.return_date, q.adults)
            outs, backs, cur = {}, {}, "GBP"
            for p in pages:
                a, b, cur = parse(p, q.departure, q.return_date)
                for j in a:
                    outs.setdefault(j["id"], j)
                for j in b:
                    backs.setdefault(j["id"], j)
            if not outs or (q.return_date and not backs):
                continue
            url = deeplink(o, d, q.departure, q.return_date, q.adults, slug)
            for a in sorted(outs.values(), key=lambda x: x["total"])[:6]:
                for b in (sorted(backs.values(), key=lambda x: x["total"])[:6] if q.return_date else [None]):
                    out.append(Itinerary(
                        source="jet2", price=round(a["total"] + (b["total"] if b else 0), 2), currency=cur,
                        slices=[_slice(a)] + ([_slice(b)] if b else []), booking_url=url, seller="Jet2.com",
                        seller_kind="airline",
                        warnings=["Jet2 fare incl. 10kg hand luggage; checked bags extra."],
                    ))
    return out
