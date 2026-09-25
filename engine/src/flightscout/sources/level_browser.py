"""LEVEL (LL, IAG's long haul low cost from Barcelona) direct from flylevel.com
through the shared real Chrome (see _browser.py). Plain HTTP clients get an
Akamai "crypto" challenge page on the flight pages (the fare calendar API is
open but only has one "from" price per day); headless Chrome solves it by
itself in a second or two.

We open the site's own flight selection URL (/Flight/Select?o1=..&d1=..) and
read the Remix loader data embedded in the server rendered page
(``window.__remixContext``): every journey with every fare family and its
``totalPrice`` (fare plus taxes and fees, all passengers). The page shows the
price rounded up to the euro (295.04 -> "€296"). Round trips come from one
page (r=true): LEVEL prices each direction on it, cheaper than two one ways.
Connecting itineraries (Vueling or Iberia feeders via BCN) are included.
About 10 to 15 seconds per search, headless.

dates() reads the site's fare calendar API (/nwe/flights/api/calendar/), which
is plain HTTP (no challenge): the cheapest one way fare per day, rounded up to
the euro like the page shows it."""

from __future__ import annotations

import json
import logging
import re
from datetime import date

from .. import cache, fx
from ..models import DatePrice, Itinerary, SearchQuery
from . import _browser
from ._airline import combine

log = logging.getLogger(__name__)
SITE = "https://www.flylevel.com"
NAMES = {"LL": "LEVEL", "VY": "Vueling", "IB": "Iberia", "I2": "Iberia Express"}
# LEVEL's long haul gateways (all flown nonstop from Barcelona) and the airports
# it sells connections from (flylevel.com route graph, September 2026).
LONGHAUL = {"BOS", "EZE", "JFK", "LAX", "LIM", "MIA", "SCL"}
FEEDERS = {
    "ACE", "AGA", "AGP", "ALC", "ALG", "AMS", "ARN", "ATH", "BCN", "BER", "BHX", "BIO", "BJZ", "BLQ", "BOD", "BRI",
    "BRU", "BSL", "CAG", "CAI", "CDG", "CPH", "CTA", "DBV", "DUB", "DUS", "EAS", "EDI", "ESU", "FAO", "FCO", "FLR",
    "FUE", "GOA", "GRX", "GVA", "HAJ", "HAM", "HER", "IBZ", "IST", "JMK", "JTR", "KEF", "LCG", "LEI", "LEN", "LGW",
    "LHR", "LIS", "LJU", "LPA", "LYS", "MAD", "MAH", "MAN", "MLA", "MLN", "MRS", "MUC", "MXP", "NAP", "NCE", "NDR",
    "NTE", "NUE", "ODB", "OLB", "OPO", "ORN", "ORY", "OVD", "PMI", "PMO", "PRG", "QSR", "RAK", "RJL", "RVN", "SCQ",
    "SDR", "SID", "SPC", "SPU", "STR", "SVQ", "SXB", "TFN", "TNG", "TOS", "TRN", "TUN", "VCE", "VGO", "VIE", "VLC",
    "VLL", "XRY", "ZRH",
}
_CTX = re.compile(r"window\.__remixContext = (\{.*?\});</script>", re.S)
_CABIN = {"economy": "Economy", "premium": "PremiumEconomy"}


def available() -> bool:
    return _browser.available()


def _routes() -> dict[str, list[str]] | None:
    return cache.get("level:routes", ttl=14 * 86400)


def has_route(o: str, d: str) -> bool:
    if (r := _routes()) is not None:
        return d in r.get(o, [])
    return (o in LONGHAUL and d in FEEDERS) or (d in LONGHAUL and o in FEEDERS)


def relevant(origins: list[str], destinations: list[str]) -> bool:
    if not available():
        return False
    return any(has_route(o, d) for o in origins for d in destinations)


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1,
             currency: str = "EUR") -> str:
    q = f"o1={origin}&d1={dest}&dd1={dep.isoformat()}"
    if ret:
        q += f"&dd2={ret.isoformat()}"
    q += (f"&ADT={adults}&CHD=0&INL=0&r={'true' if ret else 'false'}&mm=false"
          f"&forcedCurrency={currency}&forcedCulture=en-US&newecom=true")
    return f"{SITE}/Flight/Select?{q}"


def loader(html: str) -> dict:
    """The flight selection route's Remix loader data from the page HTML."""
    m = _CTX.search(html)
    if not m:
        raise ValueError("no __remixContext in the page")
    ld = json.loads(m.group(1))["state"]["loaderData"]
    return next(v for k, v in ld.items() if k.startswith("routes/Flight.Select"))


def _journeys(js: list[dict] | None, cabin: str) -> list[dict]:
    out = []
    for j in js or []:
        fares = [f for f in (j.get("fares") or {}).get(cabin) or [] if f.get("totalPrice") is not None]
        if not fares:
            continue
        f = min(fares, key=lambda x: x["totalPrice"])
        segs = [{
            "origin": s["departureStationCode"], "destination": s["arrivalStationCode"],
            "departure": s["departureDate"], "arrival": s["arrivalDate"],
            # the operating flight (LL5331 is Vueling's VY6001 sold as a LEVEL connection)
            "carrier": s.get("operatingCarrier") or s["marketingCarrier"],
            "number": (s.get("operatingNumber") if s.get("operatingCarrier") else None)
            or s.get("marketingSegmentNumber"),
            "duration": s.get("durationInMinutes"),
        } for s in j["segments"]]
        out.append({"segments": segs, "total": f["totalPrice"], "fare": f.get("group"),
                    "seats": f.get("availability"), "duration": j.get("durationInMinutes")})
    return out


def parse(data: dict, cabin: str = "economy") -> tuple[list[dict], list[dict] | None, str]:
    """Loader data -> (outbound journeys, inbound journeys or None, currency),
    cheapest fare family of the cabin per journey."""
    f = data.get("flights") or {}
    c = _CABIN.get(cabin, "Economy")
    inb = f.get("inboundJourneys")
    return (_journeys(f.get("outboundJourneys"), c), _journeys(inb, c) if inb is not None else None,
            data.get("currencyCode") or "EUR")


def _fetch(url: str) -> dict:
    def job(page) -> str:
        got = _browser.capture(page, lambda: page.goto(url, wait_until="commit", timeout=60000),
                               lambda u: u.startswith(f"{SITE}/Flight/Select?"), timeout=50,
                               body=lambda t: "window.__remixContext = " in t)
        return got[-1][1] if got else ""

    html = _browser.run(job, "level", timeout=120)
    if not html:
        raise RuntimeError("level: no flight page (Akamai challenge not passed?)")
    data = loader(html)
    routes = (data.get("routes") or {}).get("originsWithDestinations")
    if routes:
        cache.put("level:routes", {o: sorted(x["code"] for x in v) for o, v in routes.items()})
    return data


def search(q: SearchQuery) -> list[Itinerary]:
    if not relevant(q.origins, q.destinations) or q.cabin in ("business", "first"):
        return []
    cur = "EUR"
    out: list[Itinerary] = []
    pairs = [(o, d) for o in q.origins for d in q.destinations if o != d and has_route(o, d)][:3]
    for o, d in pairs:
        url = deeplink(o, d, q.departure, q.return_date, q.adults, cur)
        key = f"level:{url}"
        if (data := cache.get(key)) is None:
            data = _fetch(url)
            data = {"flights": data.get("flights"), "currencyCode": data.get("currencyCode")}
            cache.put(key, data)
        outs, backs, c = parse(data, q.cabin)
        if not outs or (q.return_date and not backs):
            continue
        fam = "Premium Light" if q.cabin == "premium" else "Economy Light"
        out += combine(q, "level", "LEVEL", outs, backs if q.return_date else None, c, url, NAMES,
                       note=f"LEVEL {fam} fare (cheapest family: carry on only, checked bag extra).")
    return out


def _calendar_month(origin: str, dest: str, year: int, month: int) -> list[dict]:
    from curl_cffi import requests as cr

    key = f"level:cal:{origin}:{dest}:{year}-{month:02d}"
    if (hit := cache.get(key, ttl=6 * 3600)) is not None:
        return hit
    r = cr.get(f"{SITE}/nwe/flights/api/calendar/", params={
        "triptype": "OW", "origin": origin, "destination": dest, "month": f"{month:02d}", "year": year,
        "currencyCode": "EUR", "originType": "flights"}, impersonate="chrome", timeout=30)
    r.raise_for_status()
    out = [d for d in (r.json().get("data") or {}).get("dayPrices") or [] if d.get("price")]
    cache.put(key, out)
    return out


def dates(origin: str, dest: str, start: date, end: date, currency: str = "EUR") -> list[DatePrice]:
    """LEVEL's own low fare calendar: cheapest one way fare per day (EUR)."""
    if not has_route(origin, dest):
        return []
    out, seen = [], set()
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        for d in _calendar_month(origin, dest, y, m):
            day = date.fromisoformat(d["date"])
            if start <= day <= end and day not in seen:
                seen.add(day)
                price = float(d["price"])
                if currency.upper() != "EUR":
                    price = fx.convert(price, "EUR", currency)
                out.append(DatePrice(origin=origin, destination=dest, departure=day, price=round(price, 2),
                                     currency=currency.upper(), source="level",
                                     booking_url=deeplink(origin, dest, day)))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return sorted(out, key=lambda x: x.departure)
