"""Wizz Air (W6) low fare calendar from wizzair.com's own backend
(be.wizzair.com/<build>/Api). Keyless, but requests must look like Chrome at
the TLS level (curl_cffi impersonation).

Only the calendar endpoints are open: /search/timetable (lowest fare per day
plus that day's departure times) and /asset/farechart. The real availability
search (/search/search) sits behind Kasada bot protection and answers 429 even
to a headless browser, so this module offers dates() and no search(). Google
Flights and Kiwi both carry priced Wizz itineraries, so the calendar is a
complement (cheap day finder, airline-direct link), not a gap filler.

Prices are the regular (non Wizz Discount Club) lowest fare for one adult in
the departure country's currency, which is what the site shows on its
calendar. The checkout total can differ slightly (a payment/admin fee may be
added), so treat the numbers as indicative."""

from __future__ import annotations

import re
import threading
from datetime import date, timedelta

from curl_cffi import requests as cr

from .. import cache, fx
from ..models import DatePrice

_HOME = "https://www.wizzair.com/en-gb"
_HEADERS = {"Origin": "https://www.wizzair.com", "Referer": _HOME + "/",
            "Accept": "application/json", "Content-Type": "application/json"}
_lock = threading.Lock()
_session: cr.Session | None = None


def _sess() -> cr.Session:
    global _session
    with _lock:
        if _session is None:
            _session = cr.Session(impersonate="chrome")
        return _session


def _base() -> str:
    """The API path carries the site build number, which changes with each
    release. Read it from the home page and keep it for a few hours."""
    key = "wizzair:build"
    if (hit := cache.get(key, ttl=4 * 3600)) is not None:
        return hit
    html = _sess().get(_HOME, timeout=30).text
    m = re.search(r"be\.wizzair\.com/(\d+\.\d+\.\d+)", html)
    if not m:
        raise RuntimeError("wizzair: build number not found on home page")
    base = f"https://be.wizzair.com/{m.group(1)}/Api"
    cache.put(key, base)
    return base


def _headers() -> dict:
    """After the first call the backend sets a RequestVerificationToken
    cookie and rejects later calls (400 InvalidProtocol) unless the same
    value comes back as a header, like the site's own JS does."""
    h = dict(_HEADERS)
    if tok := _sess().cookies.get("RequestVerificationToken"):
        h["X-RequestVerificationToken"] = tok
    return h


def _routes() -> dict[str, set[str]]:
    key = "wizzair:map"
    data = cache.get(key, ttl=24 * 3600)
    if data is None:
        r = _sess().get(f"{_base()}/asset/map?languageCode=en-gb", headers=_headers(), timeout=30)
        r.raise_for_status()
        data = {c["iata"]: [x["iata"] for x in c.get("connections") or []] for c in r.json()["cities"]}
        cache.put(key, data)
    return {k: set(v) for k, v in data.items()}


def relevant(origins: list[str], destinations: list[str]) -> bool:
    """True when Wizz flies at least one origin to destination pair nonstop."""
    try:
        net = _routes()
    except Exception:
        return False
    return any(d in net.get(o, ()) for o in origins for d in destinations)


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1) -> str:
    return (f"https://www.wizzair.com/en-gb/booking/select-flight/{origin}/{dest}/{dep.isoformat()}/"
            f"{ret.isoformat() if ret else 'null'}/{adults}/0/0/null")


def _timetable(origin: str, dest: str, start: date, end: date) -> list[dict]:
    key = f"wizzair-tt:{origin}:{dest}:{start}:{end}"
    if (hit := cache.get(key, ttl=6 * 3600)) is not None:
        return hit
    out: list[dict] = []
    day = start
    while day <= end:  # the endpoint accepts at most 29 days between from and to
        # "to" must be after "from" (a one day range answers 400)
        chunk_end = max(min(end, day + timedelta(days=29)), day + timedelta(days=1))
        body = {"flightList": [{"departureStation": origin, "arrivalStation": dest,
                                "from": day.isoformat(), "to": chunk_end.isoformat()}],
                "priceType": "regular", "adultCount": 1, "childCount": 0, "infantCount": 0}
        r = _sess().post(f"{_base()}/search/timetable", json=body, headers=_headers(), timeout=30)
        r.raise_for_status()
        out.extend(f for f in r.json().get("outboundFlights") or []
                   if f.get("departureDate", "")[:10] <= end.isoformat())
        day = chunk_end + timedelta(days=1)
    cache.put(key, out)
    return out


def dates(origin: str, dest: str, start: date, end: date, currency: str = "EUR") -> list[DatePrice]:
    """Lowest Wizz fare per departure day in [start, end]. The timetable
    answers for nearby airports on both ends too (asking KTW to LTN also
    returns KRK and LGW days), so rows for other airports are dropped."""
    out: list[DatePrice] = []
    for f in _timetable(origin, dest, start, end):
        if (f.get("departureStation"), f.get("arrivalStation")) != (origin, dest) or f.get("priceType") != "price":
            continue  # "soldOut" / "checkPrice" rows have no usable price
        p = f.get("price") or {}
        amount, cur = p.get("amount"), p.get("currencyCode")
        if not amount or not cur:
            continue
        day = date.fromisoformat(f["departureDate"][:10])
        price = fx.convert(amount, cur, currency) if cur.upper() != currency.upper() else amount
        out.append(DatePrice(origin=origin, destination=dest, departure=day, price=round(price, 2),
                             currency=currency.upper(), source="wizzair",
                             booking_url=deeplink(origin, dest, day)))
    return sorted(out, key=lambda x: x.departure)


def departures(origin: str, dest: str, day: date) -> list[str]:
    """Departure times (local, ISO) Wizz operates on a day, from the timetable."""
    for f in _timetable(origin, dest, day, day):
        if (f.get("departureStation"), f.get("arrivalStation")) == (origin, dest) and f["departureDate"][:10] == day.isoformat():
            return list(f.get("departureDates") or [])
    return []
