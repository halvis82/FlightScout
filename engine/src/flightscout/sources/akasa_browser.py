"""Akasa Air (QP) direct from akasaair.com through the shared real Chrome (see
_browser.py). The booking backend (prod-bl.qp.akasaair.com, Navitaire dotREZ
behind a thin "ibe" API) answers 403 to plain HTTP clients, token call
included, and the site has no search deeplink (the search lives in the app's
state). So we load akasaair.com headless, let the site mint its own anonymous
session token (it stores it in sessionStorage), and from that page post the
exact availability request the site's flight search sends
(/api/ibe/availability/search, same body). One request per direction.

Prices: dotREZ ``fareAmount`` per adult, which is the fare plus taxes, airport
fees and Akasa's per passenger, per segment convenience fee (service charge
WFE). The flight list and fare summary show the price before that fee ("A
non-refundable convenience fee ... will be added before checkout"), e.g.
BOM-BLR QP1149 on 20 Oct 2026: page ₹5,050, fee ₹350, we report ₹5,400.
About 15 seconds for the first search (page load), 2 to 3 after."""

from __future__ import annotations

import json
import logging
import time
from datetime import date

from .. import cache
from ..models import Itinerary, SearchQuery
from . import _browser
from ._airline import combine
from ._f_navitaire import parse_availability

log = logging.getLogger(__name__)
SITE = "https://www.akasaair.com"
API = "https://prod-bl.qp.akasaair.com/api"
NAMES = {"QP": "Akasa Air"}
# Akasa stations (the site's markets list, September 2026). Refreshed from the
# live markets list whenever a search runs.
STATIONS = {
    "AMD", "AUH", "AYJ", "BBI", "BLR", "BOM", "CCJ", "CCU", "CJB", "COK", "DBR", "DEL", "DIB", "DOH", "DXN",
    "GAU", "GOP", "GOX", "GWL", "HAN", "HKT", "HYD", "IDR", "IXA", "IXB", "IXC", "IXD", "IXR", "IXZ", "JAI",
    "JED", "KWI", "LKO", "MAA", "MED", "NAG", "NMI", "PNQ", "RPR", "RUH", "SXR", "TRZ", "UDR", "VNS", "VTZ",
}
ABROAD = {"AUH", "DOH", "HAN", "HKT", "JED", "KWI", "MED", "RUH"}
_TOKEN_MAX_AGE = 10 * 60  # the site's tokens idle out after 15 minutes
_token_at = 0.0


def available() -> bool:
    return _browser.available()


def _stations() -> set[str]:
    live = cache.get("akasa:stations", ttl=7 * 86400)
    return set(live) if live else STATIONS


def relevant(origins: list[str], destinations: list[str]) -> bool:
    if not available():
        return False
    st = _stations()
    o = [c for c in origins if c in st]
    d = [c for c in destinations if c in st]
    return bool(o and d) and any(c not in ABROAD for c in o + d)


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1) -> str:
    """Akasa has no search deeplink: the home page with the booking widget."""
    return f"{SITE}/"


def body(origin: str, dest: str, day: date, adults: int, currency: str = "INR") -> dict:
    """The availability request the site's own flight search sends."""
    return {
        "criteria": [{
            "stations": {"originStationCodes": [origin], "destinationStationCodes": [dest],
                         "searchDestinationMacs": True, "searchOriginMacs": True},
            "dates": {"beginDate": f"{day.isoformat()}T00:00:00"},
            "filters": {"compressionType": 1, "maxConnections": 8, "productClasses": ["NB", "LB", "EC", "AV"],
                        "fareTypes": ["NB", "LB", "R", "V"]},
        }],
        "passengers": {"types": [{"type": "ADT", "count": adults}], "residentCountry": ""},
        "codes": {"currencyCode": currency, "promotionCode": ""},
        "offerCode": None, "numberOfFaresPerJourney": 10, "taxesAndFees": 1,
    }


def parse(data: dict, adults: int = 1) -> tuple[list[dict], str | None]:
    d = data.get("data") or {}
    trips = parse_availability(d, adults)
    return (trips[0] if trips else []), d.get("currencyCode")


_FETCH = """async ([url, method, body]) => {
  const tok = sessionStorage.getItem('token');
  const r = await fetch(url, {method, credentials: 'omit',
    headers: {'Content-Type': 'application/json', 'Accept': 'application/json', 'authorization': tok || ''},
    body: body ? JSON.stringify(body) : undefined});
  return [r.status, await r.text()];
}"""


def _ensure_session(page) -> None:
    global _token_at
    fresh = time.time() - _token_at < _TOKEN_MAX_AGE
    if fresh and page.url.startswith(SITE):
        try:
            if page.evaluate("() => !!sessionStorage.getItem('token')"):
                return
        except Exception:
            pass
    page.goto(f"{SITE}/", wait_until="domcontentloaded", timeout=60000)
    end = time.time() + 40
    while time.time() < end:
        try:
            if page.evaluate("() => !!sessionStorage.getItem('token')"):
                _token_at = time.time()
                return
        except Exception:
            pass
        page.wait_for_timeout(500)
    raise RuntimeError("akasa: the site did not create a session token")


def _fetch(origin: str, dest: str, day: date, adults: int) -> dict:
    def job(page) -> tuple[int, str, str]:
        global _token_at
        _ensure_session(page)
        status, txt = page.evaluate(_FETCH, [f"{API}/ibe/availability/search", "POST",
                                             body(origin, dest, day, adults)])
        if status in (401, 403, 440):  # token expired: new session, once
            _token_at = 0
            _ensure_session(page)
            status, txt = page.evaluate(_FETCH, [f"{API}/ibe/availability/search", "POST",
                                                 body(origin, dest, day, adults)])
        markets = ""
        if cache.get("akasa:stations", ttl=7 * 86400) is None:
            try:
                ms, markets = page.evaluate(_FETCH, [f"{API}/nsk/v2/resources/markets?ActiveOnly=true", "GET", None])
                markets = markets if ms == 200 else ""
            except Exception as e:
                log.debug("akasa markets: %s", e)
        return status, txt, markets

    status, txt, markets = _browser.run(job, "akasa", timeout=120)
    if markets:
        try:
            ms = json.loads(markets)["data"]
            st = sorted({m["locationCode"] for m in ms if not m.get("inActive")}
                        | {m["travelLocationCode"] for m in ms if not m.get("inActive")})
            if st:
                cache.put("akasa:stations", st)
        except (ValueError, KeyError, TypeError):
            pass
    if status != 200:
        raise RuntimeError(f"akasa: availability HTTP {status} {txt[:120]!r}")
    return json.loads(txt)


def _bound(o: str, d: str, day: date, adults: int) -> tuple[list[dict], str | None]:
    key = f"akasa:{o}:{d}:{day}:{adults}"
    if (hit := cache.get(key)) is None:
        hit = _fetch(o, d, day, adults)
        cache.put(key, hit)
    js, cur = parse(hit, adults)
    # the site searches whole cities (BOM also returns Navi Mumbai, NMI): keep
    # the airports asked for, FlightScout expands nearby airports itself
    return [j for j in js if j["segments"][0]["origin"] == o and j["segments"][-1]["destination"] == d], cur


def search(q: SearchQuery) -> list[Itinerary]:
    if not relevant(q.origins, q.destinations):
        return []
    st = _stations()
    out: list[Itinerary] = []
    for o in [c for c in q.origins if c in st][:2]:
        for d in [c for c in q.destinations if c in st][:2]:
            if o == d or (o in ABROAD and d in ABROAD):
                continue
            outs, c1 = _bound(o, d, q.departure, q.adults)
            backs, _ = _bound(d, o, q.return_date, q.adults) if q.return_date and outs else (None, None)
            if not outs or (q.return_date and not backs):
                continue
            out += combine(q, "akasa", "Akasa Air", outs, backs, c1 or "INR", deeplink(o, d, q.departure), NAMES,
                           note="Akasa cheapest fare (usually Saver), incl. the convenience fee added at checkout."
                                " Search on akasaair.com (no deeplink).")
    return out
