"""Aegean Airlines (A3, and its regional Olympic Air OA) direct from
aegeanair.com through the shared real Chrome (see _browser.py). Both the site
and the Amadeus booking engine behind it (e-ticket.aegeanair.com) sit behind
Akamai, and the search is a multi step form post into an Amadeus e-Retail
session, so we let headless Chrome walk it.

The site's own search handler accepts a GET with the booking form's fields
(/srv/posthandler/flight/search?...), which returns an auto submitting form
into the booking engine; that app then fetches ``fromCalendarPage.json``: the
flights of the day with every fare family's total price (all passengers,
taxes included), exactly the "Economy from € 49.62" of the flight page. One
way and round trips are "one way combinable" there (each direction priced on
its own), so a round trip is one page with two bounds. About 15 to 30 seconds
per search, headless.

Caveat: the booking engine sits behind Imperva too, which starts answering
with a captcha page ("Pardon our interruption") after a handful of automated
searches from one IP in a short time; we then raise a clear error instead of
waiting (no captcha solving).

Times in the JSON are epoch milliseconds of the local wall clock."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from urllib.parse import urlencode

from .. import airports, cache
from ..models import Itinerary, SearchQuery
from . import _browser
from ._airline import combine

log = logging.getLogger(__name__)
SITE = "https://en.aegeanair.com"
NAMES = {"A3": "Aegean Airlines", "OA": "Olympic Air"}
# Aegean always touches Greece or Cyprus (its bases); the rest of its network
# is Europe, the Middle East, North Africa and a few long hauls.
HOME = {"GR", "CY"}


def available() -> bool:
    return _browser.available()


def relevant(origins: list[str], destinations: list[str]) -> bool:
    if not available():
        return False
    o = {a.country for c in origins if (a := airports.get(c))}
    d = {a.country for c in destinations if (a := airports.get(c))}
    return bool(o and d and (o | d) & HOME)


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1,
             currency: str = "EUR") -> str:
    f = {"flow": "Booking", "lang": "3", "AdultsNum": adults, "Children16Nums": 0, "Children12Nums": 0,
         "InfantsNum": 0, "Currency": currency, "TravelType": "R" if ret else "O", "AirportFrom": origin,
         "AirportTo": dest, "DateDeparture": f"{dep:%d/%m/%Y}"}
    if ret:
        f["DateReturn"] = f"{ret:%d/%m/%Y}"
    return f"{SITE}/srv/posthandler/flight/search?language=en&{urlencode(f)}"


def _local(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).replace(tzinfo=None).isoformat()


def _code(loc: str) -> str:
    return loc.split("_", 1)[-1]


def parse(data: dict, cabin: str = "economy") -> list[list[dict]]:
    """fromCalendarPage.json -> journeys per bound (outbound, inbound...),
    cheapest fare family of the cabin per flight."""
    mo = (data.get("bom") or {}).get("modelObject") or {}
    bounds = ((mo.get("availabilities") or {}).get("upsell") or {}).get("bounds") or []
    biz = cabin in ("business", "first")
    out = []
    for b in bounds:
        recs = {str(r.get("id")): r for r in (b.get("recommendations") or {}).values()}
        flights = {f["id"]: f for f in b.get("flights") or []}
        best: dict[int, tuple] = {}
        for a in (b.get("associations") or {}).values():
            r = recs.get(str(a.get("recoId")))
            if not r:
                continue
            try:
                p = r["recommendationPrice"]["price"]["totalPrice"]["cashAmount"]
            except (KeyError, TypeError):
                continue
            for ba in a.get("boundAssociations") or []:
                ff = ba.get("fareFamily") or r.get("fareFamily") or ""
                if ff.startswith("BUSINES") != biz:
                    continue
                fid = ba.get("flightId")
                if fid in flights and (fid not in best or p["amount"] < best[fid][0]):
                    best[fid] = (p["amount"], p.get("currency"), ff)
        js = []
        for fid, (amount, cur, ff) in best.items():
            f = flights[fid]
            segs = [{
                "origin": _code(s["originLocation"]), "destination": _code(s["destinationLocation"]),
                "departure": _local(s["flightIdentifier"]["originDate"]), "arrival": _local(s["destinationDate"]),
                "carrier": s["flightIdentifier"]["marketingAirline"], "number": s["flightIdentifier"]["flightNumber"],
                "duration": s["duration"] // 60000 if s.get("duration") else None, "aircraft": s.get("equipment"),
            } for s in f["segments"]]
            js.append({"segments": segs, "total": round(amount, 2), "currency": cur, "fare": ff,
                       "duration": f["duration"] // 60000 if f.get("duration") else None})
        out.append(sorted(js, key=lambda x: x["segments"][0]["departure"]))
    return out


def _blocked(page) -> bool:
    try:
        return bool(page.evaluate(
            "() => !!document.body && document.body.innerText.includes('Pardon our interruption')"))
    except Exception:  # navigation in progress
        return False


def _fetch(url: str) -> dict:
    def job(page) -> tuple[str, bool]:
        if "aegeanair.com" not in page.url:
            # land on the site first, like a visitor does
            page.goto(f"{SITE}/plan/book-a-flight/", wait_until="commit", timeout=60000)
            page.wait_for_timeout(6000)
        got = _browser.capture(page, lambda: page.goto(url, wait_until="commit", timeout=60000),
                               lambda u: "fromCalendarPage.json" in u, timeout=60, stop=lambda: _blocked(page))
        return (got[-1][1] if got else ""), _blocked(page)

    txt, blocked = _browser.run(job, "aegean", timeout=150)
    if blocked:
        raise RuntimeError("aegean: the booking engine's bot check (Imperva) asked for a captcha; try later")
    if not txt:
        raise RuntimeError("aegean: no availability response from the booking engine")
    d = json.loads(txt)
    mo = (d.get("bom") or {}).get("modelObject") or {}
    if mo.get("isContainingErrors") and not (mo.get("availabilities") or {}).get("upsell"):
        return {}  # no flights that day (the page shows an error message instead)
    return d


def search(q: SearchQuery) -> list[Itinerary]:
    if not relevant(q.origins, q.destinations) or q.cabin == "premium":
        return []
    cur = "EUR"
    out: list[Itinerary] = []
    for o in q.origins[:2]:
        for d in q.destinations[:2]:
            if o == d:
                continue
            url = deeplink(o, d, q.departure, q.return_date, q.adults, cur)
            key = f"aegean:{url}:{q.cabin}"
            if (bounds := cache.get(key)) is None:
                data = _fetch(url)
                bounds = parse(data, q.cabin) if data else []
                cache.put(key, bounds)
            if not bounds or not bounds[0] or (q.return_date and (len(bounds) < 2 or not bounds[1])):
                continue
            c = bounds[0][0].get("currency") or cur
            out += combine(q, "aegean", "Aegean Airlines", bounds[0], bounds[1] if q.return_date else None, c,
                           url, NAMES, note="Aegean cheapest fare family of the cabin (Light: no checked bag).")
    return out
