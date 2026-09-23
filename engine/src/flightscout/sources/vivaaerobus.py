"""VivaAerobus (VB) low fare calendar, direct from api.vivaaerobus.com.

Only the calendar works without a browser. The flight list endpoint
(/web/v1/availability/search) sits behind Akamai Bot Manager and answers 403
to curl_cffi, and even headless Chromium gets a connection reset, so there is
no ``search()`` here: Google Flights already prices VivaAerobus flights.

The calendar endpoint (/web/v1/availability/lowfares) is public: the
x-api-key below is the site's published web key, and the Akamai cookies
(_abck, bm_sz) come from one GET of the home page. ``fareWithTua`` is the
lowest fare of the day including the TUA airport fee, which is what the
calendar on vivaaerobus.com shows. Bags and seat fees are extra."""

from __future__ import annotations

import os

import threading
import time
from datetime import date, timedelta

from curl_cffi import requests as cr

from .. import airports, cache, fx
from ..models import DatePrice

API = "https://api.vivaaerobus.com/web"
HOME = "https://www.vivaaerobus.com/en-us"
_HEADERS = {
    # The web app's public gateway key, kept out of this public repo. Set
    # FLIGHTSCOUT_VIVA_KEY to enable this source (see vivaaerobus.com requests
    # in browser dev tools, header x-api-key).
    "x-api-key": os.environ.get("FLIGHTSCOUT_VIVA_KEY", ""),
    "X-Channel": "web", "Origin": "https://www.vivaaerobus.com",
    "Referer": "https://www.vivaaerobus.com/", "Accept": "application/json",
}
_lock = threading.Lock()
_session: tuple[cr.Session, float] | None = None
_last = 0.0

# VivaAerobus flies within Mexico and from Mexico to the US, Colombia, Peru,
# Guatemala and Cuba. One end must be in Mexico.
COUNTRIES = {"MX", "US", "CO", "PE", "GT", "CU"}


def relevant(origins: list[str], destinations: list[str]) -> bool:
    if not _HEADERS["x-api-key"]:
        return False

    def cc(codes):
        return {a.country for c in codes if (a := airports.get(c))}
    o, d = cc(origins), cc(destinations)
    return bool(o and d and (o | d) <= COUNTRIES and "MX" in (o | d))


def _sess() -> cr.Session:
    """Session with fresh Akamai cookies (refreshed every 20 minutes)."""
    global _session, _last
    with _lock:
        if not _session or time.time() - _session[1] > 20 * 60:
            s = cr.Session(impersonate="chrome")
            s.get(HOME, timeout=20)
            _session = (s, time.time())
        wait = 0.6 - (time.time() - _last)
        if wait > 0:
            time.sleep(wait)
        _last = time.time()
        return _session[0]


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1) -> str:
    """Opens the flight list on vivaaerobus.com (format taken from the site's own
    itineraryCode parser in main.js: journeys
    ORIGIN_DEST_YYYYMMDD joined with '.')."""
    code = f"{origin}_{dest}_{dep:%Y%m%d}"
    if ret:
        code += f".{dest}_{origin}_{ret:%Y%m%d}"
    return f"https://www.vivaaerobus.com/en-us/book/options?itineraryCode={code}&passengers=A{adults}"


def _api_currency(cur: str) -> str:
    return "USD" if cur.upper() == "USD" else "MXN"


def _lowfares(origin: str, dest: str, start: date, end: date, cur: str) -> list[dict]:
    key = f"vivaaerobus-lf:{origin}:{dest}:{start}:{end}:{cur}"
    if (hit := cache.get(key, ttl=6 * 3600)) is not None:
        return hit
    body = {
        "currencyCode": cur, "promoCode": None, "bookingType": None,
        "passengers": [{"code": "ADT", "count": 1}],
        "routes": [{"startDate": start.isoformat(), "endDate": end.isoformat(),
                    "origin": {"code": origin, "type": "Airport"},
                    "destination": {"code": dest, "type": "Airport"}}],
    }
    s = _sess()
    r = s.post(f"{API}/v1/availability/lowfares", headers=_HEADERS, json=body, timeout=30)
    if r.status_code == 403:  # Akamai cookie went stale; retry once with a new session
        global _session
        with _lock:
            _session = None
        r = _sess().post(f"{API}/v1/availability/lowfares", headers=_HEADERS, json=body, timeout=30)
    r.raise_for_status()
    out = []
    for f in (r.json().get("data") or {}).get("lowFares") or []:
        fw = f.get("fareWithTua") or {}
        if not fw.get("amount") or not f.get("availableCount"):
            continue
        out.append({"date": f["departureDate"][:10], "price": fw["amount"], "seats": f["availableCount"]})
    cache.put(key, out)
    return out


def dates(origin: str, dest: str, start: date, end: date, currency: str = "MXN") -> list[DatePrice]:
    """Lowest one way fare per day, TUA included, one adult."""
    cur = _api_currency(currency)
    out: list[DatePrice] = []
    day = start
    while day <= end:
        chunk_end = min(end, day + timedelta(days=15))  # the site asks in half month chunks
        for x in _lowfares(origin, dest, day, chunk_end, cur):
            d = date.fromisoformat(x["date"])
            if not (start <= d <= end):
                continue
            price = x["price"] if currency.upper() == cur else fx.convert(x["price"], cur, currency)
            out.append(DatePrice(origin=origin, destination=dest, departure=d, price=round(price, 2),
                                 currency=currency.upper(), source="vivaaerobus",
                                 booking_url=deeplink(origin, dest, d)))
        day = chunk_end + timedelta(days=1)
    return sorted(out, key=lambda x: x.departure)
