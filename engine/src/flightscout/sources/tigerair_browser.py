"""Tigerair Taiwan (IT) direct from tigerairtw.com through the shared real
Chrome (see _browser.py). Google Flights shows Tigerair Taiwan but often
without a price, and Kiwi only sells part of its network.

The booking app (booking.tigerairtw.com, Navitaire underneath) takes a plain
deeplink (?outbound=TPE-NRT&departureDate=...), starts a search session over
GraphQL on api-book.tigerairtw.com (the page adds its own invisible reCAPTCHA
v3 token, which is why a real browser is needed) and then fetches
``appFlightSearchResult``: every flight with each fare family (tigerlight,
tigersmart, tigerpro) and its per passenger price split into fare and tax. We
capture that JSON. About 10 to 15 seconds per search, headless.

The results page shows the fare before tax (e.g. IT202 TPE-NRT "USD 162.79")
and adds the tax in the cart after a fare is picked (USD 199.34). We report
the all in ``totalAmount`` of the cheapest family, times the adults. The
network and currency lookups are plain JSON on api-book.tigerairtw.com.
Round trips come from one round trip search, priced per direction."""

from __future__ import annotations

import json
import logging
from datetime import date

from curl_cffi import requests as cr

from .. import cache
from ..models import Itinerary, SearchQuery
from . import _browser
from ._airline import combine

log = logging.getLogger(__name__)
SITE = "https://booking.tigerairtw.com"
API = "https://api-book.tigerairtw.com/api"
NAMES = {"IT": "Tigerair Taiwan"}
CURRENCY = "TWD"  # the airline's own currency; the app prices every route in it
_H = {"Origin": SITE, "Referer": SITE + "/", "Accept": "application/json"}
# Fallback when the station list endpoint is down (September 2026).
_FALLBACK = {
    "TW": {"TPE", "RMQ", "KHH", "TNN"},
    "abroad": {"NRT", "HND", "KIX", "OKJ", "YGJ", "KCZ", "CTS", "HKD", "SDJ", "AXT", "HNA", "FKS", "KIJ", "FUK",
               "HSG", "KMI", "OIT", "KMJ", "NGO", "KMQ", "OKA", "ISG", "GMP", "ICN", "PUS", "CJU", "HKT", "DAD",
               "BKK", "DMK", "CNX", "MFM", "HKG", "SGN", "HAN", "CXR", "PQC", "MNL", "CEB", "KUL"},
}


def _get(path: str) -> dict:
    r = cr.get(f"{API}{path}", headers=_H, impersonate="chrome", timeout=20)
    r.raise_for_status()
    return r.json()


def _stations(menu: dict) -> dict[str, str]:
    """station-menu JSON -> {airport: country}."""
    out = {}
    for c in next(iter(menu["data"].values())):
        for m in c.get("stationMenus") or []:
            if m.get("station"):
                out[m["station"]["stationCode"]] = c["country"]["code2"]
    return out


def network() -> dict[str, str]:
    key = "tigerair:stations"
    if (hit := cache.get(key, ttl=7 * 86400)) is not None:
        return hit
    try:
        net = _stations(_get("/general/station-menu-countries?locale=en-US"))
        if net:
            cache.put(key, net)
            return net
    except Exception as e:
        log.debug("tigerair stations: %s", e)
    return {c: ("TW" if c in _FALLBACK["TW"] else "XX") for s in _FALLBACK.values() for c in s}


def destinations(origin: str) -> set[str]:
    """Airports Tigerair Taiwan flies to from ``origin`` (its own route list)."""
    key = f"tigerair:dest:{origin}"
    if (hit := cache.get(key, ttl=3 * 86400)) is not None:
        return set(hit)
    try:
        dest = set(_stations(_get(f"/general/available-destinations?locale=en-US&origin={origin}")))
    except Exception as e:
        log.debug("tigerair destinations %s: %s", origin, e)
        return set(network())  # let the live search decide
    cache.put(key, sorted(dest))
    return dest


def available() -> bool:
    return _browser.available()


def relevant(origins: list[str], destinations_: list[str]) -> bool:
    """Both sides on the network and one of them in Taiwan (every Tigerair
    Taiwan route touches Taiwan)."""
    if not available():
        return False
    net = network()
    o = [c for c in origins if c in net]
    d = [c for c in destinations_ if c in net]
    return bool(o and d) and any(net[c] == "TW" for c in o + d)


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1,
             currency: str = CURRENCY) -> str:
    q = f"outbound={origin}-{dest}&departureDate={dep.isoformat()}"
    if ret:
        q += f"&returnDate={ret.isoformat()}"
    return f"{SITE}/?{q}&adult={adults}&type={'roundTrip' if ret else 'oneWay'}&language=en-US&currencyCode={currency}"


def parse(data: dict, adults: int = 1) -> tuple[list[list[dict]], str | None]:
    """appFlightSearchResult JSON -> (journeys per direction, currency). Each
    journey keeps the cheapest sellable fare family, total for all adults."""
    res = (data.get("data") or {}).get("appFlightSearchResult") or {}
    dirs: list[list[dict]] = []
    currency = None
    for j in res.get("journeys") or []:
        for leg in j.get("legs") or []:
            out = []
            for al in leg.get("availabilityLegs") or []:
                best = None
                for f in al.get("fares") or []:
                    if not f.get("sellable", True):
                        continue
                    adt = next((p for p in f.get("paxFares") or [] if p.get("paxType") == "ADT"), None)
                    if not adt:
                        continue
                    tp = adt["ticketPrice"]
                    p = tp.get("discountedTotalAmount") or tp["totalAmount"]
                    if best is None or p < best[0]:
                        best = (p, tp.get("userCurrency"), f.get("productClass"), f.get("availableCount"))
                if not best:
                    continue
                segs = [{
                    "origin": s["origin"], "destination": s["destination"],
                    "departure": s["departureTime"].replace(" ", "T"), "arrival": s["arrivalTime"].replace(" ", "T"),
                    "carrier": s["carrierCode"], "number": s["flightNumber"].strip(), "duration": s.get("duration"),
                    "aircraft": ((s.get("availabilitySegmentDetails") or [{}])[0] or {}).get("equipmentType"),
                } for s in al["availabilitySegments"]]
                out.append({"segments": segs, "total": round(best[0] * adults, 2), "fare": best[2],
                            "seats": best[3], "duration": al.get("duration")})
                currency = currency or best[1]
            dirs.append(out)
    return dirs, currency


def _fetch(url: str) -> dict:
    def job(page) -> str:
        got = _browser.capture(page, lambda: page.goto(url, wait_until="commit", timeout=45000),
                               lambda u: "api-book.tigerairtw.com/graphql" in u, timeout=45,
                               body=lambda t: '"appFlightSearchResult"' in t)
        return got[-1][1] if got else ""

    txt = _browser.run(job, "tigerair", timeout=120)
    if not txt:
        raise RuntimeError("tigerair: no flight search response from booking.tigerairtw.com")
    d = json.loads(txt)
    if d.get("errors") and not (d.get("data") or {}).get("appFlightSearchResult"):
        raise RuntimeError(f"tigerair: error response {txt[:150]!r}")
    return d


def search(q: SearchQuery) -> list[Itinerary]:
    if not relevant(q.origins, q.destinations):
        return []
    net = network()
    out: list[Itinerary] = []
    for o in [c for c in q.origins if c in net][:2]:
        for d in [c for c in q.destinations if c in net][:2]:
            if o == d or d not in destinations(o) or "TW" not in (net[o], net[d]):
                continue
            url = deeplink(o, d, q.departure, q.return_date, q.adults)
            key = f"tigerair:{o}:{d}:{q.departure}:{q.return_date}:{q.adults}"
            if (data := cache.get(key)) is None:
                data = _fetch(url)
                cache.put(key, data)
            dirs, cur = parse(data, q.adults)
            outs = dirs[0] if dirs else []
            backs = (dirs[1] if len(dirs) > 1 else []) if q.return_date else None
            if not outs or (q.return_date and not backs):
                continue
            out += combine(q, "tigerair", "Tigerair Taiwan", outs, backs, cur or CURRENCY, url, NAMES,
                           note="Tigerair Taiwan cheapest fare family (usually tigerlight: 10 kg carry on, "
                                "checked bags extra).")
    return out
