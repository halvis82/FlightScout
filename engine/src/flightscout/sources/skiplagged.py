"""Skiplagged (skiplagged.com): normal fares plus "hidden city" (skiplagging)
fares, through the JSON endpoint its own results page calls,
/api/search.php (keyless; Cloudflare lets Chrome TLS through, curl_cffi).

One GET per route returns every itinerary with its price in cents (USD, the
total for all passengers incl. taxes, exactly the "$79" on the results page)
and the full ticketed segment list. A hidden city itinerary is a ticket to a
city beyond the one asked for: the ``count`` field says how many of its
segments the traveler flies (e.g. SAN-SEA-PDX sold as SAN to SEA, count 1,
get off in Seattle). We keep only the flown segments in the slice and flag
the itinerary loudly: carry-on only, the rest of the ticket must be skipped,
airlines can cancel onward and return segments of a skipped ticket.

Round trips: with a return date the same call lists the outbound flights
with a "from" round trip minimum and the return flights with their one way
prices. Like the page does when you pick an outbound, we POST that outbound
to /api/search_lazy.php (one request each, for the 3 cheapest regular
outbounds) and get the real round trip price of every return. Hidden city
outbounds can't be on a round trip ticket: the page prices them as the
outbound one way plus a return one way (two tickets), and so do we.

Unofficial: fails soft."""

from __future__ import annotations

import threading
import time
from datetime import date, datetime

from curl_cffi import requests as cr

from .. import cache
from ..models import Itinerary, SearchQuery, Segment, Slice

SITE = "https://skiplagged.com"
API = SITE + "/api/search.php"
LAZY = SITE + "/api/search_lazy.php"
SELLER = "Skiplagged"
HIDDEN = ("hidden city: don't check bags, final leg must be skipped. The ticket is to {final} via {dest}: "
          "get off at {dest}, carry-on only, don't book it as a round trip, and don't add a frequent flyer "
          "number (airlines can cancel the rest of the ticket).")
TWO_OW = ("Two separate one way tickets on Skiplagged (outbound and return priced alone): a delay or "
          "cancellation on one does not protect the other.")
_local = threading.local()


def relevant(origins: list[str], destinations: list[str]) -> bool:
    return True  # every market, strongest in the US


def _session() -> cr.Session:
    if not hasattr(_local, "s"):
        _local.s = cr.Session(impersonate="chrome")
    return _local.s


def search_url(o: str, d: str, dep: date, ret: date | None = None, adults: int = 1) -> str:
    u = f"{SITE}/flights/{o}/{d}/{dep.isoformat()}" + (f"/{ret.isoformat()}" if ret else "")
    return u + (f"?adults={adults}" if adults > 1 else "")


def _fetch(o: str, d: str, dep: date, ret: date | None, adults: int) -> dict:
    key = f"skiplagged:{o}:{d}:{dep}:{ret}:{adults}"
    if (hit := cache.get(key, ttl=20 * 60)) is not None:
        return hit
    params = {"from": o, "to": d, "depart": dep.isoformat(), "return": ret.isoformat() if ret else "",
              "format": "v3", "counts[adults]": str(adults), "counts[children]": "0"}
    last = ""
    for _ in range(2):
        r = _session().get(API, params=params, timeout=40, headers={
            "Accept": "application/json", "Referer": search_url(o, d, dep, ret)})
        if r.status_code in (429, 500, 502, 503, 504):
            last = f"HTTP {r.status_code}"
            time.sleep(2)
            continue
        if r.status_code != 200 or "json" not in r.headers.get("content-type", ""):
            raise RuntimeError(f"skiplagged: HTTP {r.status_code} {r.text[:120]!r}")
        data = r.json()
        if not isinstance(data.get("itineraries"), dict):
            raise RuntimeError(f"skiplagged: {str(data)[:200]}")
        cache.put(key, data)
        return data
    raise RuntimeError(f"skiplagged: no response ({last})")


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def journey(flight: dict, names: dict[str, str]) -> tuple[Slice, str | None]:
    """(slice of the flown segments, ticketed final airport when hidden city)."""
    segs = flight.get("segments") or []
    flown = max(1, min(int(flight.get("count") or len(segs)), len(segs)))
    out = []
    for s in segs[:flown]:
        dep, arr = s["departure"]["time"], s["arrival"]["time"]
        out.append(Segment(
            origin=s["departure"]["airport"], destination=s["arrival"]["airport"],
            departure=_dt(dep).replace(tzinfo=None), arrival=_dt(arr).replace(tzinfo=None),
            carrier=s["airline"], carrier_name=names.get(s["airline"]), flight_number=str(s["flight_number"]),
            duration_min=int(s.get("duration") or (_dt(arr) - _dt(dep)).total_seconds()) // 60,
        ))
    total = int((_dt(segs[flown - 1]["arrival"]["time"]) - _dt(segs[0]["departure"]["time"])).total_seconds() // 60)
    final = segs[-1]["arrival"]["airport"] if flown < len(segs) else None
    return Slice(segments=out, duration_min=max(1, total)), final


def _flights(data: dict, side: str) -> list[tuple[dict, dict]]:
    """(itinerary row, flight) pairs of one side of a search.php answer."""
    flights = data.get("flights") or {}
    return [(it, flights[it["flight"]]) for it in (data.get("itineraries") or {}).get(side) or []
            if it.get("flight") in flights and (flights[it["flight"]].get("segments"))]


def _ok(sl: Slice, o: str, d: str, max_stops: int | None) -> bool:
    return sl.origin == o and sl.destination == d and (max_stops is None or sl.stops <= max_stops)


def _names(data: dict) -> dict[str, str]:
    return {k: (v or {}).get("name") for k, v in (data.get("airlines") or {}).items()}


def _side(data: dict, side: str, o: str, d: str, max_stops: int | None,
          price: str = "one_way_price") -> list[tuple[float, Slice, str | None, dict, dict]]:
    """(price, flown slice, hidden city final airport, row, flight), cheapest first."""
    names = _names(data)
    out = []
    for it, f in _flights(data, side):
        if it.get(price) is None:
            continue
        try:
            sl, final = journey(f, names)
        except (KeyError, ValueError, TypeError):
            continue
        if _ok(sl, o, d, max_stops):
            out.append((round(float(it[price]) / 100, 2), sl, final, it, f))
    return sorted(out, key=lambda x: x[0])


def _it(q: SearchQuery, price: float, slices: list[Slice], url: str, warn: list[str], split: bool = False):
    return Itinerary(source="skiplagged", price=price, currency="USD", slices=slices, booking_url=url,
                     seller=SELLER, seller_kind="metasearch", self_transfer=split, warnings=warn)


def parse(data: dict, q: SearchQuery, o: str, d: str, lazy: dict[str, dict] | None = None,
          limit: int = 6) -> list[Itinerary]:
    """search.php JSON (+ search_lazy.php answers keyed by outbound flight
    key, for round trips) -> Itineraries between exactly ``o`` and ``d``."""
    url = search_url(o, d, q.departure, q.return_date, q.adults)
    res = []
    if not q.return_date:
        for price, sl, final, _, _ in _side(data, "outbound", o, d, q.max_stops)[:40]:
            res.append(_it(q, price, [sl], url, [HIDDEN.format(final=final, dest=d)] if final else []))
        return res
    # hidden city outbounds: outbound one way + return one way, two tickets
    backs = [b for b in _side(data, "inbound", d, o, q.max_stops) if not b[2]][:3]
    hidden = [x for x in _side(data, "outbound", o, d, q.max_stops) if x[2]][:3]
    for p1, s1, f1, _, _ in hidden:
        for p2, s2, _, _, _ in backs:
            res.append(_it(q, round(p1 + p2, 2), [s1, s2], url, [TWO_OW, HIDDEN.format(final=f1, dest=d)], True))
    # regular outbounds: the round trip price of each return, from search_lazy
    for key, ans in (lazy or {}).items():
        names = _names(ans)
        flights = ans.get("flights") or {}
        for row in (ans.get("itineraries") or {}).get("outbound") or []:
            fo = flights.get(row.get("flight")) or (data.get("flights") or {}).get(row.get("flight"))
            if not fo:
                continue
            s1, f1 = journey(fo, _names(data) | names)
            if f1 or not _ok(s1, o, d, q.max_stops):
                continue
            rows = sorted((x for x in row.get("inbound") or [] if x.get("round_trip_price") is not None),
                          key=lambda x: x["round_trip_price"])
            n = 0
            for x in rows:
                fb = flights.get(x.get("flight"))
                if not fb or n >= limit:
                    continue
                s2, f2 = journey(fb, names)
                if not _ok(s2, d, o, q.max_stops):
                    continue
                n += 1
                warn = [HIDDEN.format(final=f2, dest=o)] if f2 else []
                res.append(_it(q, round(float(x["round_trip_price"]) / 100, 2), [s1, s2], url, warn))
    return res


def _lazy(o: str, d: str, dep: date, ret: date, adults: int, row: dict, flight: dict) -> dict:
    """The page's "select this outbound" call: round trip price per return."""
    key = f"skiplagged:lazy:{o}:{d}:{dep}:{ret}:{adults}:{row.get('flight')}"
    if (hit := cache.get(key, ttl=20 * 60)) is not None:
        return hit
    r = _session().post(f"{LAZY}?return={ret.isoformat()}&format=v3", data={"trip": flight["data"],
                        "tripMeta": row["data"]}, timeout=40,
                        headers={"Referer": search_url(o, d, dep, ret), "X-Requested-With": "XMLHttpRequest"})
    if r.status_code != 200 or "json" not in r.headers.get("content-type", ""):
        raise RuntimeError(f"skiplagged: round trip prices HTTP {r.status_code}")
    data = r.json()
    cache.put(key, data)
    return data


def _route(q: SearchQuery, o: str, d: str) -> list[Itinerary]:
    data = _fetch(o, d, q.departure, q.return_date, q.adults)
    lazy: dict[str, dict] = {}
    if q.return_date:
        regular = [x for x in _side(data, "outbound", o, d, q.max_stops, "min_round_trip_price") if not x[2]]
        for _, _, _, row, flight in regular[:3]:
            if row.get("data") and flight.get("data"):
                try:
                    lazy[row["flight"]] = _lazy(o, d, q.departure, q.return_date, q.adults, row, flight)
                except Exception:
                    continue
    return parse(data, q, o, d, lazy)


def search(q: SearchQuery) -> list[Itinerary]:
    if q.cabin != "economy":
        return []  # Skiplagged sells economy only
    out: list[Itinerary] = []
    for o in q.origins[:2]:
        for d in q.destinations[:2]:
            if o != d:
                out += _route(q, o, d)
    return sorted(out, key=lambda i: i.price)
