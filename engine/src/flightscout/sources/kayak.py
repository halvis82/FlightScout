"""KAYAK Explore ("where can I go") through the JSON endpoint behind
kayak.com/explore (keyless, Chrome TLS impersonation). One request returns the
cheapest recent round trip fare to 100 to 400 destinations (about 2,000 with
no dates), in well under a second. Prices are cached from KAYAK users'
recent searches (not live), so treat them as leads and confirm with a search.

The endpoint answers 400 unless exactDates and zoomLevel are present. The
market comes from the domain: kayak.com prices in USD, kayak.no in NOK, and
so on (see _DOMAINS). Round trips only."""

from __future__ import annotations

import threading
from datetime import date, datetime

from curl_cffi import requests as cr

from .. import airports, cache, fx
from ..models import Destination

PATH = "/s/horizon/exploreapi/destinations"
# Currency -> KAYAK site that prices in it. Anything else uses kayak.com (USD)
# and gets converted.
_DOMAINS = {
    "USD": "www.kayak.com", "NOK": "www.kayak.no", "SEK": "www.kayak.se", "DKK": "www.kayak.dk",
    "EUR": "www.kayak.de", "GBP": "www.kayak.co.uk", "MXN": "www.kayak.com.mx", "CAD": "www.ca.kayak.com",
    "AUD": "www.kayak.com.au", "CHF": "www.kayak.ch", "PLN": "www.kayak.pl", "BRL": "www.kayak.com.br",
    "JPY": "www.kayak.co.jp", "INR": "www.kayak.co.in",
}
_local = threading.local()


def _session() -> cr.Session:
    if not hasattr(_local, "s"):
        _local.s = cr.Session(impersonate="chrome")
    return _local.s


def booking_url(domain: str, origin: str, dest: str, dep: date, ret: date | None) -> str:
    tail = f"/{dep.isoformat()}" + (f"/{ret.isoformat()}" if ret else "")
    return f"https://{domain}/flights/{origin}-{dest}{tail}?sort=price_a"


def _raw(domain: str, origin: str, start: date | None, end: date | None, nonstop: bool,
         duration: int | None) -> list[dict]:
    params = {"airport": origin, "exactDates": "false", "zoomLevel": "2"}
    if start and end:
        params.update(depart=start.strftime("%Y%m%d"), **{"return": end.strftime("%Y%m%d")})
    if duration:
        params["duration"] = str(duration)
    if nonstop:
        params.update(flightMaxStops="0", stopsFilterActive="true")
    key = "kayak:" + domain + ":" + ":".join(f"{k}={v}" for k, v in sorted(params.items()))
    if (hit := cache.get(key, ttl=6 * 3600)) is not None:
        return hit
    r = _session().get(f"https://{domain}{PATH}", params=params, timeout=25,
                       headers={"Accept": "application/json", "Referer": f"https://{domain}/explore/{origin}-anywhere"})
    if r.status_code != 200 or not r.headers.get("content-type", "").startswith("application/json"):
        raise RuntimeError(f"kayak explore HTTP {r.status_code}")
    out = r.json().get("destinations") or []
    cache.put(key, out)
    return out


def explore(origin: str, start: date | None, end: date | None, currency: str = "USD",
            nights: tuple[int, int] | None = None, nonstop: bool = False) -> list[Destination]:
    """Cheapest cached round trip to every destination KAYAK knows from
    ``origin`` with both flights inside [start, end]. ``nights`` narrows to
    trips of that length (KAYAK takes a single length, so we ask for the
    middle and filter)."""
    cur = currency.upper()
    domain = _DOMAINS.get(cur, "www.kayak.com")
    api_cur = cur if cur in _DOMAINS else "USD"
    duration = round((nights[0] + nights[1]) / 2) if nights else None
    out: list[Destination] = []
    for x in _raw(domain, origin, start, end, nonstop, duration):
        info = x.get("flightInfo") or {}
        ap_ = x.get("airport") or {}
        code = ap_.get("shortName")
        if not code or info.get("priceless") or not info.get("price"):
            continue
        try:
            dep = datetime.strptime(x["departd"], "%Y%m%d").date()
            ret = datetime.strptime(x["returnd"], "%Y%m%d").date() if x.get("returnd") else None
        except (KeyError, ValueError):
            continue
        if nights and ret and not nights[0] <= (ret - dep).days <= nights[1]:
            continue
        if start and end and not (start <= dep <= end):
            continue
        ap = airports.get(code)
        if not ap:  # metro rows (PAR, LON, MIL) repeat an airport row
            continue
        price = float(info["price"])
        if api_cur != cur:
            price = round(fx.convert(price, api_cur, cur), 2)
        out.append(Destination(
            origin=origin, destination=code, city=(x.get("city") or {}).get("name") or (ap.city if ap else None),
            country=(x.get("country") or {}).get("code") or (ap.country if ap else None),
            price=price, currency=cur, departure=dep, return_date=ret, source="kayak",
            booking_url=booking_url(domain, origin, code, dep, ret),
            lat=ap_.get("latitude") or (ap.lat if ap else None), lon=ap_.get("longitude") or (ap.lon if ap else None),
        ))
    return out
