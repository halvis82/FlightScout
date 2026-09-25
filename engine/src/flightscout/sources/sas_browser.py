"""SAS (SK) through flysas.com's own flight selection page in the shared
headless Chrome. The page (behind Cloudflare) loads its offers from
/api/offers/flights; we read that answer, or, when the page stalls on
"Searching" (it does now and then), call the same URL from inside the page
so it carries the page's cookies. One page load per direction, 10 to 30
seconds.

Each outbound flight lists its cabins (ECONOMY, PREMIUM, BUSINESS) and fare
products (SAS Go Light, SAS Go, ...) with totalPrice for all passengers incl.
taxes: the cheapest product of the asked cabin is the "Economy €79,32" on
the page. flysas.com picks the market (and currency, EUR for most) from the
visitor. Round trips are priced as two one ways (SAS sells each direction on
its own fare inside Europe; long haul round trips can be cheaper on the
site).

Unofficial and flaky (Cloudflare): fails soft."""

from __future__ import annotations

import json
from datetime import date

from .. import cache
from ..models import Itinerary, SearchQuery
from . import _browser
from ._airline import combine, countries

SITE = "https://www.flysas.com"
NAMES = {"SK": "SAS", "WF": "Widerøe", "DX": "DAT"}
_CABIN = {"economy": "ECONOMY", "premium": "PREMIUM", "business": "BUSINESS", "first": "BUSINESS"}
HOME = {"NO", "SE", "DK"}


def relevant(origins: list[str], destinations: list[str]) -> bool:
    return _browser.available() and bool((countries(origins) | countries(destinations)) & HOME)


def deeplink(o: str, d: str, dep: date, ret: date | None = None, adults: int = 1) -> str:
    s = (f"RT_{o}-{d}-{dep:%Y%m%d}-{ret:%Y%m%d}" if ret else f"OW_{o}-{d}-{dep:%Y%m%d}") + f"_a{adults}c0i0y0"
    return f"{SITE}/en/book/flights/?search={s}&view=upsell&bookingFlow=revenue&sortBy=stop,stop"


def parse(data: dict, cabin: str = "economy") -> tuple[list[dict], str]:
    """/api/offers/flights JSON -> (journeys for _airline.combine, currency)."""
    want = _CABIN.get(cabin, "ECONOMY")
    cur = (data.get("currency") or {}).get("code") or "EUR"
    out = []
    for f in (data.get("outboundFlights") or {}).values():
        if f.get("isSoldOut"):
            continue
        best = None
        for fam in ((f.get("cabins") or {}).get(want) or {}).values():
            for p in (fam.get("products") or {}).values():
                pr = (p.get("price") or {}).get("totalPrice")
                if pr is None:
                    continue
                seats = min((x.get("avlSeats") or 99 for x in p.get("fares") or []), default=None)
                if best is None or pr < best[0]:
                    best = (float(pr), p.get("productName"), seats)
        if best is None:
            continue
        segs = [{"origin": s["departureAirport"]["code"], "destination": s["arrivalAirport"]["code"],
                 "departure": s["departureDateTimeInLocal"], "arrival": s["arrivalDateTimeInLocal"],
                 "carrier": (s.get("marketingCarrier") or {}).get("code") or "SK", "number": s["flightNumber"],
                 "aircraft": (s.get("airCraft") or {}).get("name")} for s in f.get("segments") or []]
        if segs:
            out.append({"segments": segs, "total": round(best[0], 2), "fare": best[1], "seats": best[2]})
    return out, cur


def _bound(o: str, d: str, day: date, adults: int) -> dict:
    key = f"sas:{o}:{d}:{day}:{adults}"
    if (hit := cache.get(key)) is not None:
        return hit
    url = deeplink(o, d, day, None, adults)
    api = (f"/api/offers/flights?to={d}&from={o}&outDate={day:%Y%m%d}&adt={adults}&chd=0&inf=0&yth=0"
           f"&bookingFlow=revenue&channel=web&displayType=upsell")

    def job(page):
        got = _browser.capture(page, lambda: page.goto(url, wait_until="domcontentloaded", timeout=45000),
                               lambda u: "/api/offers/flights" in u, timeout=30)
        if got:
            return got[-1][1]
        try:
            status, text = page.evaluate("""async (u) => { const r = await fetch(u, {headers: {accept: 'application/json'}});
                                            return [r.status, await r.text()]; }""", api)
        except Exception as e:
            raise RuntimeError(f"sas: no offers, the page stalled (Cloudflare?): {str(e)[:80]}") from None
        if status != 200:
            raise RuntimeError(f"sas: offers HTTP {status} (Cloudflare?)")
        return text

    hit = json.loads(_browser.run(job, "sas", timeout=110))
    if "outboundFlights" not in hit:
        raise RuntimeError(f"sas: {str(hit)[:150]}")
    cache.put(key, hit)
    return hit


def search(q: SearchQuery) -> list[Itinerary]:
    if not relevant(q.origins, q.destinations):
        return []
    out: list[Itinerary] = []
    for o in q.origins[:1]:
        for d in q.destinations[:1]:
            if o == d:
                continue
            outs, cur = parse(_bound(o, d, q.departure, q.adults), q.cabin)
            backs = None
            if q.return_date:
                if not outs:
                    continue
                backs, cur2 = parse(_bound(d, o, q.return_date, q.adults), q.cabin)
                if not backs or cur2 != cur:
                    continue
            out += combine(q, "sas", "SAS", outs, backs, cur, deeplink(o, d, q.departure, q.return_date, q.adults),
                           NAMES, note="SAS's cheapest fare in the cabin (usually SAS Go Light: no checked bag).")
    return out
