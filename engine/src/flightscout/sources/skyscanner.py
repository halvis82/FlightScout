"""Skyscanner month view price calendar (the grid behind "Whole month" on
skyscanner.net), keyless with Chrome TLS impersonation.

One request prices every day of a month for any route, with the carrier and
the agent that quoted it. Prices are Skyscanner's cache of recent searches
(each cell carries its fetch time, we drop cells older than MAX_AGE_DAYS),
which makes it good at catching fares Google does not price, such as
Volaris, Frontier or Wizz Air quotes from OTAs. Leads, not bookable prices:
confirm with a live search. Search and explore endpoints on Skyscanner are
behind PerimeterX and are not used."""

from __future__ import annotations

import threading
from datetime import date, datetime, timedelta

from curl_cffi import requests as cr

from .. import airports, cache
from ..models import DatePrice

BASE = "https://www.skyscanner.net/g/monthviewservice"
MAX_AGE_DAYS = 10
_local = threading.local()


def relevant(origins: list[str], destinations: list[str]) -> bool:
    return True  # every market


def _session() -> cr.Session:
    if not hasattr(_local, "s"):
        _local.s = cr.Session(impersonate="chrome")
    return _local.s


def booking_url(origin: str, dest: str, dep: date, ret: date | None = None) -> str:
    u = f"https://www.skyscanner.net/transport/flights/{origin.lower()}/{dest.lower()}/{dep:%y%m%d}/"
    if ret:
        u += f"{ret:%y%m%d}/"
    return u + "?adultsv2=1&cabinclass=economy&rtn=" + ("1" if ret else "0")


def _market(origin: str) -> str:
    ap = airports.get(origin)
    return ap.country if ap else "US"


def _month(origin: str, dest: str, month: str, currency: str) -> dict:
    mkt = _market(origin)
    key = f"skyscanner:{mkt}:{currency}:{origin}:{dest}:{month}"
    if (hit := cache.get(key, ttl=6 * 3600)) is not None:
        return hit
    r = _session().get(f"{BASE}/{mkt}/{currency.upper()}/en-GB/calendar/{origin}/{dest}/{month}/",
                       params={"profile": "minimalmonthviewgridv2"}, timeout=25,
                       headers={"Accept": "application/json", "Referer": "https://www.skyscanner.net/"})
    if r.status_code != 200:
        raise RuntimeError(f"skyscanner calendar HTTP {r.status_code}")
    d = r.json()
    cache.put(key, d)
    return d


def _trace(t: str) -> tuple[datetime | None, str | None]:
    """'{bl}:202609230908*I*SAN*MEX*20261101*skyp*F9' -> (fetched at, carrier)."""
    try:
        parts = t.split(":", 1)[1].split("|")[0].split("*")
        return datetime.strptime(parts[0], "%Y%m%d%H%M"), parts[6]
    except (IndexError, ValueError):
        return None, None


def dates(origin: str, dest: str, start: date, end: date, currency: str = "USD",
          direct_only: bool = False) -> list[DatePrice]:
    """Cheapest cached one way fare per day between start and end."""
    out: list[DatePrice] = []
    stale = datetime.now() - timedelta(days=MAX_AGE_DAYS)
    m = date(start.year, start.month, 1)
    while m <= end:
        d = _month(origin, dest, m.strftime("%Y-%m"), currency)
        traces = d.get("Traces") or {}
        grid = (d.get("PriceGrids") or {}).get("Grid") or [[]]
        for i, cell in enumerate(grid[0]):
            day = m + timedelta(days=i)
            if not (start <= day <= end) or day < date.today():
                continue
            best = None
            for kind in (("Direct",) if direct_only else ("Direct", "Indirect")):
                c = cell.get(kind) or {}
                if not c.get("Price"):
                    continue
                fetched, _ = _trace(traces.get((c.get("TraceRefs") or [""])[0], ""))
                if fetched and fetched < stale:
                    continue
                if best is None or c["Price"] < best:
                    best = c["Price"]
            if best:
                out.append(DatePrice(origin=origin, destination=dest, departure=day, price=float(best),
                                     currency=currency.upper(), source="skyscanner",
                                     booking_url=booking_url(origin, dest, day)))
        m = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
    return out
