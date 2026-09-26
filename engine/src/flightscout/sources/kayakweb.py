"""KAYAK flight search results (the full itinerary search, not Explore) and
its sister metasearch sites on the same platform, momondo and Cheapflights,
over plain HTTP (keyless, Chrome TLS impersonation).

The results page (/flights/LAX-JFK/2026-11-06) carries a per session CSRF
``formtoken`` in its HTML. With it we POST the same poll the page makes
(/i/api/search/dynamic/flights/poll) until KAYAK says ``complete``: usually
two polls, 5 to 12 seconds in all, 3 requests per route. Each result is one
itinerary with every provider's live price (airline sites and OTAs); we keep
the cheapest as the Itinerary price and seller and put the per provider
prices in ``offers``. ``fees.totalPrice`` is the total for all passengers,
exactly what the results page shows.

The market (and currency) comes from the domain: kayak.com prices in USD,
kayak.no in NOK and so on (see BRANDS). Other currencies use the .com site
and search() converts. Unofficial: fails soft."""

from __future__ import annotations

import re
import threading
import time
from datetime import date, datetime

from curl_cffi import requests as cr

from .. import cache
from ..models import Fare, Itinerary, Offer, SearchQuery, Segment, Slice

POLL = "/i/api/search/dynamic/flights/poll"
BRANDS: dict[str, dict] = {
    "kayakweb": {"name": "KAYAK", "path": "flights", "domains": {
        "USD": "www.kayak.com", "NOK": "www.kayak.no", "SEK": "www.kayak.se", "DKK": "www.kayak.dk",
        "EUR": "www.kayak.de", "GBP": "www.kayak.co.uk", "MXN": "www.kayak.com.mx", "CAD": "www.ca.kayak.com",
        "AUD": "www.kayak.com.au", "CHF": "www.kayak.ch", "PLN": "www.kayak.pl", "BRL": "www.kayak.com.br",
        "JPY": "www.kayak.co.jp", "INR": "www.kayak.co.in"}},
    "momondo": {"name": "momondo", "path": "flight-search", "domains": {
        "USD": "www.momondo.com", "NOK": "www.momondo.no", "SEK": "www.momondo.se", "DKK": "www.momondo.dk",
        "EUR": "www.momondo.de", "GBP": "www.momondo.co.uk", "CAD": "www.momondo.ca", "AUD": "www.momondo.com.au",
        "CHF": "www.momondo.ch", "PLN": "www.momondo.pl", "MXN": "www.momondo.mx"}},
    "cheapflights": {"name": "Cheapflights", "path": "flight-search", "domains": {
        "USD": "www.cheapflights.com", "GBP": "www.cheapflights.co.uk", "CAD": "www.cheapflights.ca",
        "AUD": "www.cheapflights.com.au"}},
}
_CABIN = {"economy": "e", "premium": "p", "business": "b", "first": "f"}
_CABIN_API = {"premium": "premium", "business": "business", "first": "first"}  # economy: omitted
_local = threading.local()
HACKER = ("KAYAK \"Hacker Fare\": two separate one way tickets, a missed connection or schedule change "
          "on one is not covered by the other.")


def relevant(origins: list[str], destinations: list[str]) -> bool:
    return True  # every market


def _session(brand: str) -> cr.Session:
    key = "s_" + brand
    if not hasattr(_local, key):
        setattr(_local, key, cr.Session(impersonate="chrome"))
    return getattr(_local, key)


def domain(brand: str, currency: str) -> tuple[str, str]:
    """(host, currency it prices in) for ``brand`` and the wanted currency."""
    doms = BRANDS[brand]["domains"]
    cur = currency.upper()
    return (doms[cur], cur) if cur in doms else (doms["USD"], "USD")


def search_url(brand: str, host: str, o: str, d: str, dep: date, ret: date | None = None, adults: int = 1,
               cabin: str = "economy", result_id: str | None = None) -> str:
    path = f"/{BRANDS[brand]['path']}/{o}-{d}/{dep.isoformat()}" + (f"/{ret.isoformat()}" if ret else "")
    if cabin != "economy":
        path += "/" + {"premium": "premium", "business": "business", "first": "first"}[cabin]
    if adults > 1:
        path += f"/{adults}adults"
    if result_id:
        path += f"/f{result_id}"
    return f"https://{host}{path}?sort=price_a"


def _body(o: str, d: str, dep: date, ret: date | None, adults: int, cabin: str, search_id: str | None) -> dict:
    def leg(a, b, day):
        x = {"origin": {"airports": [a], "locationType": "airports"},
             "destination": {"airports": [b], "locationType": "airports"}, "date": day.isoformat(), "flex": "exact"}
        if cabin in _CABIN_API:
            x["cabinClass"] = _CABIN_API[cabin]
        return x
    usp = {"legs": [leg(o, d, dep)] + ([leg(d, o, ret)] if ret else []), "passengers": ["ADT"] * adults,
           "passengerDetails": [{"ptc": "ADT"}] * adults, "sortMode": "price_a"}
    if search_id:
        usp["searchId"] = search_id
    return {"filterParams": {}, "userSearchParams": usp,
            "searchMetaData": {"pageNumber": 1, "searchTypes": [], "skipResultsInSecondPhase": True}}


def _fetch(brand: str, host: str, o: str, d: str, dep: date, ret: date | None, adults: int, cabin: str) -> dict:
    key = f"kayakweb:{host}:{o}:{d}:{dep}:{ret}:{adults}:{cabin}"
    if (hit := cache.get(key, ttl=20 * 60)) is not None:
        return hit
    s = _session(brand)
    page = search_url(brand, host, o, d, dep, ret, adults, cabin)
    r = s.get(page, timeout=30)
    m = re.search(r'"formtoken":"([^"]+)"', r.text)
    if r.status_code != 200 or not m:
        raise RuntimeError(f"{brand}: results page HTTP {r.status_code}, no form token (bot check?)")
    hdr = {"Origin": f"https://{host}", "Referer": page, "Accept": "application/json", "X-CSRF": m.group(1)}
    sid, data, end = None, {}, time.time() + 45
    while time.time() < end:
        r = s.post(f"https://{host}{POLL}", json=_body(o, d, dep, ret, adults, cabin, sid), headers=hdr, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"{brand}: poll HTTP {r.status_code} {r.text[:150]!r}")
        data = r.json()
        sid = data.get("searchId") or sid
        if data.get("status") == "complete":
            break
        time.sleep(2.5)
    if data.get("status") != "complete" and not data.get("results"):
        raise RuntimeError(f"{brand}: search did not complete")
    if data.get("status") == "complete":  # a partial answer is shown, not remembered
        cache.put(key, data)
    return data


def _slice(leg_id: str, data: dict) -> Slice:
    leg = data["legs"][leg_id]
    segs = []
    for ref in leg["segments"]:
        s = data["segments"][ref["id"]]
        segs.append(Segment(
            origin=s["origin"], destination=s["destination"], departure=datetime.fromisoformat(s["departure"]),
            arrival=datetime.fromisoformat(s["arrival"]), carrier=s["airline"],
            carrier_name=(data.get("airlines") or {}).get(s["airline"], {}).get("name"),
            flight_number=str(s.get("flightNumber") or "") or None, duration_min=s.get("duration"),
            aircraft=s.get("equipmentTypeName"),
        ))
    return Slice(segments=segs, duration_min=max(1, int(leg.get("duration") or 0)))


def parse(data: dict, q: SearchQuery, brand: str, host: str, o: str, d: str) -> list[Itinerary]:
    provs = data.get("providers") or {}

    def airline(pc: str) -> bool:
        return ((provs.get(pc) or {}).get("providerQualityScore") or {}).get("badgeType") == "AIRLINE"

    def label(pc: str) -> str:
        return (provs.get(pc) or {}).get("displayName") or pc

    out = []
    for r in data.get("results") or []:
        if r.get("type") != "core" or not r.get("legs") or not r.get("bookingOptions"):
            continue
        opts = []
        for b in r["bookingOptions"]:
            tp = ((b.get("fees") or {}).get("totalPrice") or {})
            if tp.get("price") is None or not b.get("providerCode"):
                continue
            opts.append((float(tp["price"]), tp.get("currency"), b["providerCode"], bool(b.get("splitBookingOptions"))))
        if not opts:
            continue
        try:
            slices = [_slice(leg["id"], data) for leg in r["legs"]]
        except KeyError:
            continue
        if slices[0].origin != o or slices[0].destination != d:
            continue  # KAYAK adds nearby airport results
        if q.return_date and (len(slices) < 2 or slices[1].origin != d or slices[1].destination != o):
            continue
        if q.max_stops is not None and any(s.stops > q.max_stops for s in slices):
            continue
        opts.sort(key=lambda x: (x[0], not airline(x[2])))  # on a tie, the airline itself
        price, cur, code, split = opts[0]
        best: dict[str, tuple[float, bool]] = {}
        for p, _, pc, _ in opts:
            best.setdefault(label(pc), (p, airline(pc)))
        offers = [Offer(seller=s, is_airline=a, fares=[Fare(price=p)]) for s, (p, a) in best.items()]
        name = BRANDS[brand]["name"]
        warn = [f"Cheapest of {len(best)} sites on {name}: {label(code)}."]
        if split:
            warn.append(HACKER)
        out.append(Itinerary(
            source=brand, price=price, currency=cur or domain(brand, q.currency)[1], slices=slices,
            booking_url=search_url(brand, host, o, d, q.departure, q.return_date, q.adults, q.cabin, r.get("resultId")),
            seller=label(code), seller_kind="airline" if airline(code) else "ota",
            self_transfer=split, offers=offers, warnings=warn,
        ))
    return out


def search_brand(brand: str, q: SearchQuery) -> list[Itinerary]:
    host, _ = domain(brand, q.currency)
    out: list[Itinerary] = []
    for o in q.origins[:2]:
        for d in q.destinations[:2]:
            if o != d:
                data = _fetch(brand, host, o, d, q.departure, q.return_date, q.adults, q.cabin)
                out += parse(data, q, brand, host, o, d)
    return sorted(out, key=lambda i: i.price)


def search(q: SearchQuery) -> list[Itinerary]:
    return search_brand("kayakweb", q)


def search_momondo(q: SearchQuery) -> list[Itinerary]:
    return search_brand("momondo", q)


def search_cheapflights(q: SearchQuery) -> list[Itinerary]:
    return search_brand("cheapflights", q)
