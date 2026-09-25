"""VietJet (VJ, and Thai VietJet VZ) direct from vietjetair.com through the
shared real Chrome (see _browser.py). The search API signs every request
(HMAC headers computed by the page's JS) and sits behind AWS WAF plus an
invisible reCAPTCHA v3 check, so plain HTTP is out. We open the site's own
affiliate deeplink (/en/affiliate?departAirport=..) headless; the app runs its
own checks and fetches /booking/api/v1/search-flight for five days around the
requested date. We keep the response for the requested day.

Prices: per adult ``fareCharges`` of the chosen fare option (fare incl. VAT,
admin, management, airport and security fees) summed, which is exactly the
"Total" the site shows after picking a fare. The optional "Seat Assignment"
charge that comes with Eco is left out, like the site does. The site tends to
auto apply a public promo, and totalAmount already reflects it.

The site is slow (40 to 90 seconds per direction headless), so round trips
are two one way loads (VietJet prices each direction on its own)."""

from __future__ import annotations

import json
import logging
from datetime import date

from .. import cache
from ..models import Itinerary, SearchQuery
from . import _browser
from ._airline import combine, countries

log = logging.getLogger(__name__)
SITE = "https://www.vietjetair.com"
NAMES = {"VJ": "VietJet Air", "VZ": "Thai VietJet"}
HOME = {"VN", "TH"}
# Where VietJet and Thai VietJet fly (September 2026 network).
COUNTRIES = HOME | {"KR", "JP", "TW", "HK", "MO", "CN", "SG", "MY", "ID", "PH", "KH", "LA", "MM", "IN", "AU",
                    "KZ", "BN", "NP", "BD", "LK", "AE", "FR", "IT", "DE"}
_OPTIONAL = {"SA"}  # seat assignment, not part of the fare total on the site


def available() -> bool:
    return _browser.available()


def relevant(origins: list[str], destinations: list[str]) -> bool:
    if not available():
        return False
    o, d = countries(origins), countries(destinations)
    return bool(o and d and (o | d) <= COUNTRIES and HOME & (o | d))


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1,
             currency: str = "VND") -> str:
    u = (f"{SITE}/en/affiliate?departAirport={origin}&arrivalAirport={dest}&departDate={dep.isoformat()}"
         f"&tripType={'roundTrip' if ret else 'oneway'}&adultCount={adults}&childCount=0&infantCount=0"
         f"&currency={currency}&languageCode=en")
    if ret:
        u = u.replace("&tripType=", f"&returnDate={ret.isoformat()}&tripType=")
    return u


def _total(fo: dict) -> tuple[float, str | None]:
    tot, cur = 0.0, None
    for c in fo.get("fareCharges") or []:
        if not (c.get("passengerApplicability") or {}).get("adult"):
            continue
        if (c.get("chargeType") or {}).get("code") in _OPTIONAL:
            continue
        amt = (c.get("currencyAmounts") or [None])[0]
        if not amt:
            continue
        tot += amt.get("totalAmount") or 0
        cur = cur or (amt.get("currency") or {}).get("code")
    return tot, cur


def parse(data: dict, origin: str, dest: str, day: date, adults: int = 1) -> tuple[list[dict], str | None]:
    """search-flight JSON -> (journeys on ``day``, currency). Each journey keeps
    its cheapest bookable fare option; totals are for ``adults`` adults."""
    out, currency = [], None
    for o in (data.get("travelOption") or {}).get(f"{origin}-{dest}") or []:
        if o.get("departureDate") != day.isoformat():
            continue
        best = None
        for fo in o.get("fareOptions") or []:
            v = fo.get("fareValidity") or {}
            if not v.get("valid", True) or v.get("soldOut") or v.get("noFare"):
                continue
            if (fo.get("availability") or 0) < adults:
                continue
            t, cur = _total(fo)
            if t and (best is None or t < best[0]):
                best = (t, cur, (fo.get("fareType") or {}).get("identifier"), fo.get("availability"))
        if not best:
            continue
        segs = [{
            "origin": f["departure"]["airport"]["code"], "destination": f["arrival"]["airport"]["code"],
            "departure": f["departure"]["localScheduledTime"].replace(" ", "T")
            + f["departure"]["airport"].get("utcOffset", {}).get("iso", ""),
            "arrival": f["arrival"]["localScheduledTime"].replace(" ", "T")
            + f["arrival"]["airport"].get("utcOffset", {}).get("iso", ""),
            "carrier": (f.get("airlineCode") or {}).get("code") or "VJ", "number": f["flightNumber"],
            "aircraft": (f.get("aircraftModel") or {}).get("name"),
        } for f in o.get("flights") or []]
        if not segs:
            continue
        out.append({"segments": segs, "total": round(best[0] * adults, 2), "fare": best[2], "seats": best[3]})
        currency = currency or best[1]
    return out, currency


def _fetch(origin: str, dest: str, day: date, adults: int) -> dict:
    url = deeplink(origin, dest, day, adults=adults)
    marker = f'"departureDate":"{day.isoformat()}"'

    def job(page) -> str:
        try:  # the app turns dates into local midnight: use Vietnam time
            page.context.new_cdp_session(page).send("Emulation.setTimezoneOverride",
                                                    {"timezoneId": "Asia/Ho_Chi_Minh"})
        except Exception as e:
            log.debug("timezone override failed: %s", e)
        got = _browser.capture(page, lambda: page.goto(url, wait_until="commit", timeout=60000),
                               lambda u: "/booking/api/v1/search-flight" in u, timeout=150,
                               body=lambda t: marker in t or '"travelOption":{}' in t)
        return got[-1][1] if got else ""

    txt = _browser.run(job, "vietjet", timeout=240)
    if not txt:
        raise RuntimeError("vietjet: no search-flight response")
    d = json.loads(txt)
    if not d.get("status", True) and "travelOption" not in d:
        raise RuntimeError(f"vietjet: error response {txt[:150]!r}")
    return d


def _bound(o: str, d: str, day: date, adults: int) -> tuple[list[dict], str | None]:
    key = f"vietjet:{o}:{d}:{day}:{adults}"
    if (hit := cache.get(key)) is None:
        hit = _fetch(o, d, day, adults)
        cache.put(key, hit)
    return parse(hit, o, d, day, adults)


def search(q: SearchQuery) -> list[Itinerary]:
    if not relevant(q.origins, q.destinations):
        return []
    out: list[Itinerary] = []
    for o in q.origins[:2]:
        for d in q.destinations[:2]:
            if o == d:
                continue
            outs, c1 = _bound(o, d, q.departure, q.adults)
            backs, c2 = _bound(d, o, q.return_date, q.adults) if q.return_date and outs else (None, None)
            if not outs or (q.return_date and not backs):
                continue
            if backs is not None and c2 and c1 and c2 != c1:
                continue  # never add two currencies
            out += combine(q, "vietjet", "VietJet Air", outs, backs, c1 or "VND",
                           deeplink(o, d, q.departure, q.return_date, q.adults), NAMES,
                           note="VietJet cheapest fare (usually Eco, checked bags extra).")
    return out
