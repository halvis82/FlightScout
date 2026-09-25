"""FLY91 (IC) direct from fly91.in through the shared headless Chrome (see
_browser.py). Goa based regional airline (ATR 72s from Goa Mopa, Pune,
Hyderabad, Bengaluru, Sindhudurg, Jalgaon, Agatti, ...) that Kiwi and most
OTAs don't sell.

The booking engine is IBS iFly Res (Spring Web Flow): the home page's search
button opens ``/reservation/ibe/booking?mode=searchResultInter&...``, a wait
page that posts itself and renders the flight list as server side HTML. The
listed fares ("4,199 INR") are per passenger incl. taxes but WITHOUT the
mandatory convenience fee, which the page adds only once a flight is
picked. So we open the list and, for each of the cheapest few flights, pick
it like a visitor would (one server round trip each) and read the page's
"Total ... incl. taxes, fees & surcharges" for all passengers. Verified:
GOX-HYD 5 Nov 2026, 2 adults, IC 5303 from Sindhudurg 2 x 4,199 + 2 x 298
convenience fee = Total 8,994 INR. About 20 to 30 seconds per search.

One way per page load; a round trip is two one way searches (FLY91 prices
each direction on its own)."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime

from .. import cache
from ..models import Itinerary, SearchQuery
from . import _browser
from ._airline import combine

log = logging.getLogger(__name__)
SITE = "https://fly91.in"
NAMES = {"IC": "FLY91"}
# FLY91's network (the home page's airport list, 2026-09)
AIRPORTS = {"AGX", "BLR", "BOM", "COK", "GOX", "HBX", "HYD", "JLG", "PNQ", "RJA", "SDW", "SSE", "TIR", "VGA"}
PICK = 3  # flights priced per search (one server round trip each)


def available() -> bool:
    return _browser.available()


def relevant(origins: list[str], destinations: list[str]) -> bool:
    return available() and any(o != d and o in AIRPORTS and d in AIRPORTS for o in origins for d in destinations)


def deeplink(o: str, d: str, day: date, adults: int = 1) -> str:
    return (f"{SITE}/reservation/ibe/booking?mode=searchResultInter&wvm=WVMD&tripType=OW&origin={o}"
            f"&destination={d}&travelDate={day:%d-%b-%Y}&adults={adults}&children=0&infants=0&cabinClass=ECONOMY"
            "&promoCode=&pointOfPurchase=OTHERS&channel=FLYWEB&locale=en_US&fareLevelSearch=ST&fareTypeSearch=SAVER")


def _num(s: str) -> float:
    return float(re.sub(r"[^\d.]", "", s))


def _seg(v: str) -> dict:
    """One ``selFlight`` value: 05-Nov-2026/16:30/GMT+05:30/GOX&.../18:25/
    05-Nov-2026/GMT+05:30/JLG&.../01:55/0/IC5202"""
    p = v.split("/")
    dep_day, dep_t, dep_tz, org, arr_t, arr_day, arr_tz, dst = p[:8]
    fn = p[-1]

    def iso(day: str, t: str, tz: str) -> str:
        off = tz.replace("GMT", "") or "+00:00"
        return datetime.strptime(f"{day} {t}", "%d-%b-%Y %H:%M").isoformat() + off

    h, m = (p[8].split(":") + ["0"])[:2] if len(p) > 8 else ("0", "0")
    return {"origin": org.split("&")[0], "destination": dst.split("&")[0],
            "departure": iso(dep_day, dep_t, dep_tz), "arrival": iso(arr_day, arr_t, arr_tz),
            "carrier": fn[:2], "number": fn[2:], "duration": int(h) * 60 + int(m)}


def parse(html: str) -> list[dict]:
    """Flight list HTML -> [{"segments", "fare" (per passenger, without the
    convenience fee), "radio" (the fare's input id)}], cheapest fare type per
    flight."""
    out = []
    for blk in re.split(r'<div class="flight\s[^"]*" data-faretype', html)[1:]:
        segs = [_seg(v) for v in re.findall(r'data-key="selFlight" data-value="([^"]+)"', blk)]
        fares = []
        for m in re.finditer(r'<div class="book-fare[^"]*"(.*?)(?=<div class="book-fare|$)', blk, re.S):
            amt = re.search(r'class="flightAmount">\s*([\d,.]+)\s*([A-Z]{3})', m.group(1))
            radio = re.search(r'id="(flight-[\d-]+)"', m.group(1))
            if amt and radio:
                fares.append((_num(amt.group(1)), amt.group(2), radio.group(1),
                              (re.search(r'data-fare="([^"]+)"', m.group(0)) or [None, None])[1]))
        if segs and fares:
            price, cur, radio, name = min(fares)
            out.append({"segments": segs, "fare_pp": price, "currency": cur, "radio": radio, "fare": name})
    return out


_TOTAL = re.compile(r"Total\s+([\d,]+)\s*([A-Z]{3})\s+incl")


def _fetch(o: str, d: str, day: date, adults: int) -> list[dict]:
    url = deeplink(o, d, day, adults)

    def content(page) -> str:
        try:
            return page.content()
        except Exception:  # the wait page is still posting itself
            return ""

    def job(page) -> list[dict]:
        page.goto(url, wait_until="commit", timeout=60000)
        html = ""
        for _ in range(80):
            page.wait_for_timeout(500)
            html = content(page)
            if "book-fare" in html or re.search(r"(?i)no flights? (are )?available|no flights found", html):
                break
        page.wait_for_timeout(500)
        html = content(page) or html
        flights = sorted(parse(html), key=lambda f: f["fare_pp"])
        priced = []
        for f in flights[:PICK]:
            try:
                # blank the summary, pick the flight, wait for the server's new summary
                page.evaluate("id => { const s = document.getElementById('summary'); if (s) s.innerHTML = '';"
                              " document.getElementById(id).click(); }", f["radio"])
                page.wait_for_function("() => /Total\\s+[\\d,]+\\s*[A-Z]{3}\\s+incl/.test("
                                       "(document.getElementById('summary') || {}).innerText || '')", timeout=30000)
            except Exception as e:
                log.debug("fly91: selecting %s failed: %s", f["radio"], e)
                continue
            m = _TOTAL.search(re.sub(r"\s+", " ", page.inner_text("#summary")))
            if m:
                priced.append({**f, "total": _num(m.group(1)), "currency": m.group(2)})
        return priced

    return _browser.run(job, "fly91", timeout=150)


def _bound(o: str, d: str, day: date, adults: int) -> list[dict]:
    key = f"fly91:{o}:{d}:{day}:{adults}"
    if (hit := cache.get(key)) is None:
        hit = _fetch(o, d, day, adults)
        cache.put(key, hit)
    return [j for j in hit if j["segments"][0]["origin"] == o and j["segments"][-1]["destination"] == d]


def search(q: SearchQuery) -> list[Itinerary]:
    if q.cabin != "economy" or not relevant(q.origins, q.destinations):
        return []
    out: list[Itinerary] = []
    pairs = [(o, d) for o in q.origins[:2] for d in q.destinations[:2] if o != d and o in AIRPORTS and d in AIRPORTS]
    for o, d in pairs[:2]:
        outs = _bound(o, d, q.departure, q.adults)
        backs = _bound(d, o, q.return_date, q.adults) if q.return_date and outs else None
        if not outs or (q.return_date and not backs):
            continue
        note = "FLY91 SAVER fare incl. the convenience fee."
        if q.return_date:
            note += " Priced as two one way bookings."
        out += combine(q, "fly91", "FLY91", outs, backs, outs[0]["currency"], deeplink(o, d, q.departure, q.adults),
                       NAMES, note=note)
    return out
