"""Jeju Air (7C) direct from jejuair.net through the shared real Chrome (see
_browser.py). Korea's biggest low cost carrier; Google Flights often shows it
without a price and Kiwi only sells part of its network.

The route list is plain JSON (sec.jejuair.net selectDepartureStations /
selectArrivalStations, no key). The search needs a browser: the flight page
(AvailSearch.do) is a form POST, then the page waits in its NetFunnel queue
and loads getAvailSchedule.json, an HTML fragment where every flight carries
its Navitaire segments (data-segments) and fares (data-fares) as JSON
attributes. We open Availability.do (Akamai cookies), move the mouse a bit (its
sensor wants some user activity), submit the same form the site builds and
capture that fragment. About 20 to 30 seconds per direction, headless.

``fareAmount`` per adult already includes taxes and fuel surcharge (e.g.
ICN-NRT 7C1181: fare 50,000 + BP 24,000 + YQ 57,100 = KRW 131,100, the price
on the results page). Prices are in the origin's currency (KRW from Korea).
Round trips are two one ways (Jeju Air prices each direction on its own)."""

from __future__ import annotations

import html
import json
import logging
import random
import re
from datetime import date

from curl_cffi import requests as cr

from .. import cache, fx
from ..models import Itinerary, SearchQuery
from . import _browser
from ._airline import combine

log = logging.getLogger(__name__)
SITE = "https://www.jejuair.net"
SEC = "https://sec.jejuair.net"
NAMES = {"7C": "Jeju Air"}
_H = {"Origin": SITE, "Referer": SITE + "/", "Channel-Code": "WPC"}
_SEGS = re.compile(r"data-segments\s*=\s*'(\[.*?\])'", re.S)
_FARES = re.compile(r"data-fares\s*=\s*'(\[.*?\])'", re.S)
# Fallback when the station list is down (September 2026).
_FALLBACK = {
    "KR": {"ICN", "GMP", "PUS", "CJU", "TAE", "CJJ", "KWJ", "MWX", "RSU", "USN", "KPO", "YNY", "WJU"},
    "XX": {"BKI", "BKK", "BTH", "CEB", "CNX", "CRK", "CTS", "CXR", "DAD", "DPS", "DYG", "FSZ", "FUK", "HAN",
           "HIJ", "HKD", "HKG", "HRB", "JMU", "KHH", "KIX", "KOJ", "KWL", "MFM", "MNL", "MYJ", "NGO", "NRT",
           "OIT", "OKA", "PEK", "PKX", "PQC", "PVG", "SIN", "SJW", "SPN", "TAG", "TAO", "TPE", "UBN", "UKB",
           "VTE", "WEH", "YNJ"},
}


def _post(path: str, data: dict) -> list[dict]:
    r = cr.post(f"{SEC}/en/ibe/booking/{path}", data={"bookType": "Common", "cultureCode": "en-US",
                                                      "pageId": "0000000294", **data},
                headers=_H, impersonate="chrome", timeout=20)
    r.raise_for_status()
    d = r.json()
    return ((d.get("data") or {}).get("data") or {}).get("stations") or []


def network() -> dict[str, str]:
    """Jeju Air airports -> country code, from the site's own station list."""
    key = "jejuair:stations"
    if (hit := cache.get(key, ttl=7 * 86400)) is not None:
        return hit
    try:
        net = {s["stationCode"]: s["countryCode"] for s in _post("selectDepartureStations.json", {})
               if s.get("mac") != "Y"}
        if net:
            cache.put(key, net)
            return net
    except Exception as e:
        log.debug("jejuair stations: %s", e)
    return {c: cc for cc, s in _FALLBACK.items() for c in s}


def arrivals(origin: str) -> set[str]:
    key = f"jejuair:arr:{origin}"
    if (hit := cache.get(key, ttl=3 * 86400)) is not None:
        return set(hit)
    try:
        arr = {s["stationCode"] for s in _post("selectArrivalStations.json", {"originAirport": origin, "mac": ""})}
    except Exception as e:
        log.debug("jejuair arrivals %s: %s", origin, e)
        return set(network())
    cache.put(key, sorted(arr))
    return arr


def available() -> bool:
    return _browser.available()


def relevant(origins: list[str], destinations: list[str]) -> bool:
    if not available():
        return False
    net = network()
    return any(o in net for o in origins) and any(d in net for d in destinations)


def deeplink() -> str:
    """The flight list is a form POST, so this opens the booking page."""
    return f"{SITE}/en/ibe/booking/Availability.do"


def _form(o: str, d: str, day: date, adults: int, net: dict[str, str]) -> dict:
    return {
        "tripRoute": [{"originAirport": o, "originCountryCode": net.get(o, ""), "destinationAirport": d,
                       "destinationCountryCode": net.get(d, ""), "flightDate": day.isoformat(),
                       "sortOptions": "EarliestDeparture,EarliestArrival", "depMac": "", "arrMac": ""}],
        "passengers": [{"type": "ADT", "count": str(adults)}], "tripType": "OW", "bookType": "Common",
        "domIntType": "D" if net.get(o) == net.get(d) == "KR" else "I", "cultureCode": "en-US",
        "lowfareIncludeTaxesAndFee": "false", "discountInfo": {}, "voucherInfo": {},
    }


def _iso(t: str, offset_min: int | None) -> str:
    if offset_min is None:
        return t
    sign = "+" if offset_min >= 0 else "-"
    return f"{t}{sign}{abs(offset_min) // 60:02d}:{abs(offset_min) % 60:02d}"


def parse(fragment: str, adults: int = 1) -> tuple[list[dict], str | None]:
    """getAvailSchedule.json HTML fragment -> (journeys, currency)."""
    segs_m = list(_SEGS.finditer(fragment))
    fares_m = list(_FARES.finditer(fragment))
    out, currency = [], None
    for i, m in enumerate(segs_m):
        end = segs_m[i + 1].start() if i + 1 < len(segs_m) else len(fragment)
        best = None
        for f in fares_m:
            if not m.end() < f.start() < end:
                continue
            for fa in json.loads(html.unescape(f.group(1))):
                for p in fa.get("passengerFares") or []:
                    if p.get("passengerType") != "ADT":
                        continue
                    cur = next((c.get("currencyCode") for c in p.get("serviceCharges") or []
                                if c.get("type") == "FarePrice"), None)
                    if best is None or p["fareAmount"] < best[0]:
                        best = (p["fareAmount"], cur, fa.get("productClass"))
        if not best:
            continue  # sold out
        segs = []
        for s in json.loads(html.unescape(m.group(1))):
            legs = s.get("legs") or [{}]
            first, last = (legs[0].get("legInfo") or {}), (legs[-1].get("legInfo") or {})
            segs.append({
                "origin": s["designator"]["origin"], "destination": s["designator"]["destination"],
                "departure": _iso(s["designator"]["departure"], first.get("departureTimeVariant")),
                "arrival": _iso(s["designator"]["arrival"], last.get("arrivalTimeVariant")),
                "carrier": s["identifier"]["carrierCode"], "number": s["identifier"]["identifier"].strip(),
                "aircraft": first.get("equipmentType"),
            })
        out.append({"segments": segs, "total": round(best[0] * adults, 2), "fare": best[2]})
        currency = currency or best[1]
    return out, currency


def _settle(page) -> None:
    """Akamai Bot Manager on jejuair.net resets the search POST
    (ERR_HTTP2_PROTOCOL_ERROR) when its sensor saw no user activity on the
    page, so move the mouse and scroll a little first, like a visitor
    looking at the form does."""
    page.wait_for_timeout(2500)
    for _ in range(20):
        page.mouse.move(random.randint(100, 1300), random.randint(100, 800), steps=random.randint(5, 15))
        page.wait_for_timeout(random.randint(80, 250))
    page.mouse.wheel(0, 400)
    page.wait_for_timeout(700)
    page.mouse.wheel(0, -400)
    page.wait_for_timeout(2500)


def _fetch(form: dict) -> str:
    payload = json.dumps(form)

    def job(page) -> str:
        for attempt in range(3):
            try:
                page.goto(deeplink(), wait_until="domcontentloaded", timeout=45000)
                page.wait_for_selector("#availSearchForm", state="attached", timeout=20000)
                _settle(page)
                got = _browser.capture(page, lambda: page.evaluate(
                    """d => { const f = document.getElementById('availSearchForm');
                              document.getElementById('availSearchData').value = d;
                              f.method = 'POST'; f.action = '/en/ibe/booking/AvailSearch.do'; f.submit(); }""",
                    payload), lambda u: "/getAvailSchedule.json" in u, timeout=50,
                    stop=lambda: page.url.startswith("chrome-error"))
                if got:
                    return got[-1][1]
            except Exception as e:  # Akamai sometimes resets the form POST (ERR_HTTP2_PROTOCOL_ERROR)
                log.debug("jejuair attempt %d: %s", attempt, e)
            page.wait_for_timeout(2000)
        return ""

    txt = _browser.run(job, "jejuair", timeout=240)
    if not txt:
        raise RuntimeError("jejuair: no availability response from jejuair.net")
    return txt


def _bound(o: str, d: str, day: date, adults: int, net: dict) -> tuple[list[dict], str | None]:
    key = f"jejuair:{o}:{d}:{day}:{adults}"
    if (hit := cache.get(key)) is None:
        hit = _fetch(_form(o, d, day, adults, net))
        cache.put(key, hit)
    return parse(hit, adults)


def search(q: SearchQuery) -> list[Itinerary]:
    if not relevant(q.origins, q.destinations):
        return []
    net = network()
    out: list[Itinerary] = []
    for o in [c for c in q.origins if c in net][:2]:
        for d in [c for c in q.destinations if c in net][:2]:
            if o == d or d not in arrivals(o):
                continue
            outs, c1 = _bound(o, d, q.departure, q.adults, net)
            backs, c2 = _bound(d, o, q.return_date, q.adults, net) if q.return_date and outs else (None, None)
            if not outs or (q.return_date and not backs):
                continue
            note = "Jeju Air cheapest fare (Standard: carry on only, checked bags extra)."
            if backs and c2 and c1 and c2 != c1:
                # each direction is priced in its origin's currency (KRW out, JPY back...)
                backs = [{**b, "total": round(fx.convert(b["total"], c2, c1), 2)} for b in backs]
                note += f" Return priced in {c2} by Jeju Air, converted to {c1}."
            out += combine(q, "jejuair", "Jeju Air", outs, backs, c1 or "KRW", deeplink(), NAMES, note=note)
    return out
