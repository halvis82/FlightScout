"""Wingo (P5, Copa's low cost arm) direct from wingo.com through the shared
real Chrome (see _browser.py). Wingo signs every API call in the browser (a
fresh RS256 token per request, delivered over a server sent events channel)
and sends the search itself encrypted, so there is no plain HTTP route; the
results page works in headless Chrome though.

We open the booking deeplink (booking.wingo.com/es/search/BOG/CTG/...) and
read the ``routes-api/fares`` JSON the page fetches. Playwright's response
body is empty for that call, so we pause it at the response stage with the
CDP Fetch domain and read the body there (inside the browser, nothing is
re-sent). One call covers both directions of a round trip plus three days
either side; we keep only the requested dates.

``totalAmount`` is the per adult price incl. taxes and Wingo's
administrative fee, the number the results page shows (verified: P5 7216
BOG-CTG 2026-11-10 COP 177,805 and P5 7073 BLB-BOG 2026-11-10 USD 83.42 on
the page and in the JSON). About 8 to 15 seconds per search.

Currency: COP when leaving Colombia, USD otherwise (what wingo.com uses).
Gentle: Cloudflare answers 1020 for a while after bursts of invalid searches,
so we only search airports Wingo serves."""

from __future__ import annotations

import base64
import json
import logging
import time
from datetime import date

from .. import airports, cache
from ..models import Itinerary, SearchQuery
from . import _browser
from ._airline import combine

log = logging.getLogger(__name__)
SITE = "https://booking.wingo.com"
NAMES = {"P5": "Wingo"}
# Wingo's airports (the route icons on wingo.com, Sept 2026). BLB is Panamá
# Pacífico, Wingo's Panama City airport (it does not fly to PTY).
AIRPORTS = set("""
ADZ AUA BAQ BGA BLB BOG CCS CLO CTG CUN CUR GUA HAV MDE PUJ SDQ SJO SMR VUP VLN
""".split())


def available() -> bool:
    return _browser.available()


def _pairs(origins: list[str], destinations: list[str]) -> list[tuple[str, str]]:
    return [(o, d) for o in origins for d in destinations if o in AIRPORTS and d in AIRPORTS and o != d]


def relevant(origins: list[str], destinations: list[str]) -> bool:
    return bool(_pairs(origins, destinations)) and available()


def _currency(origin: str) -> str:
    a = airports.get(origin)
    return "COP" if a and a.country == "CO" else "USD"


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1) -> str:
    cur = _currency(origin)
    if ret:
        return f"{SITE}/es/search/{origin}/{dest}/{dep}/{ret}/{adults}/0/0/0/{cur}/0/0"
    return f"{SITE}/es/search/{origin}/{dest}/{dep}/{adults}/0/0/1/{cur}/0/0"


def parse(data: dict, dep: date, ret: date | None = None, adults: int = 1) -> tuple[list[dict], list[dict], str]:
    """fares JSON -> (outbound journeys on ``dep``, return journeys on ``ret``, currency)."""
    cur = (data.get("currencyInformation") or {}).get("currency") or "COP"
    want = {"OUTBOUND": str(dep), "RETURN": str(ret) if ret else None}
    res: dict[str, list[dict]] = {"OUTBOUND": [], "RETURN": []}
    for block in data.get("dates") or []:
        kind = block.get("type")
        if kind not in res or not want.get(kind):
            continue
        for day in block.get("dates") or []:
            if (day.get("date") or "")[:10] != want[kind]:
                continue
            for f in day.get("flights") or []:
                fares = [p for p in (f.get("fares") or {}).get("faresByPtc") or []
                         if p.get("totalAmount") and p.get("seatsAvailable", 1) > 0]
                if f.get("isSoldOut") or not fares:
                    continue
                best = min(fares, key=lambda p: p["totalAmount"])
                carrier, _, number = (f.get("flightNumber") or "P5 ").partition(" ")
                res[kind].append({
                    "segments": [{"origin": f["originCode"], "destination": f["destinationCode"],
                                  "departure": f["departureDate"], "arrival": f["arrivalDate"],
                                  "carrier": carrier or "P5", "number": number.strip(),
                                  "duration": int(f["flightDuration"]) if f.get("flightDuration") else None}],
                    "total": round(float(best["totalAmount"]) * adults, 2), "seats": best.get("seatsAvailable"),
                    "fare": best.get("fareClass"),
                    "duration": int(f["flightDuration"]) if f.get("flightDuration") else None,
                })
    return res["OUTBOUND"], res["RETURN"], cur


def _fetch(url: str) -> dict:
    def job(page) -> str:
        cdp = page.context.new_cdp_session(page)
        got: list[str] = []

        def paused(e):
            rid = e["requestId"]
            try:
                if e.get("responseStatusCode") == 200 and e["request"]["method"] == "GET":
                    b = cdp.send("Fetch.getResponseBody", {"requestId": rid})
                    got.append(base64.b64decode(b["body"]).decode() if b.get("base64Encoded") else b["body"])
                elif e.get("responseStatusCode") and e["request"]["method"] == "GET":
                    log.info("wingo: fares answered %s", e["responseStatusCode"])
            except Exception as ex:
                log.debug("wingo: body unavailable: %s", ex)
            finally:
                try:
                    cdp.send("Fetch.continueRequest", {"requestId": rid})
                except Exception:
                    pass

        cdp.on("Fetch.requestPaused", paused)
        cdp.send("Fetch.enable", {"patterns": [{"urlPattern": "*gateway.wingo.com/routes-api/fares*",
                                                 "requestStage": "Response"}]})
        try:
            page.goto(url, wait_until="commit", timeout=45000)
            end = time.time() + 40
            while not got and time.time() < end:
                page.wait_for_timeout(250)
        finally:
            try:
                cdp.send("Fetch.disable")
                cdp.detach()
            except Exception:
                pass
        return got[-1] if got else ""

    txt = _browser.run(job, "wingo", timeout=100)
    if not txt:
        raise RuntimeError("wingo: no fares response (route not flown, bot check or site change)")
    return json.loads(txt)


def search(q: SearchQuery) -> list[Itinerary]:
    pairs = _pairs(q.origins, q.destinations)
    if not pairs or not available() or q.cabin != "economy":
        return []
    out: list[Itinerary] = []
    for o, d in pairs[:2]:
        key = f"wingo:{o}:{d}:{q.departure}:{q.return_date}"
        if (data := cache.get(key)) is None:
            data = _fetch(deeplink(o, d, q.departure, q.return_date))
            cache.put(key, data)
        outs, backs, cur = parse(data, q.departure, q.return_date, q.adults)
        if q.return_date and not backs:
            continue
        out += combine(q, "wingo", "Wingo", outs, backs if q.return_date else None, cur,
                       deeplink(o, d, q.departure, q.return_date, q.adults), NAMES,
                       note="Wingo cheapest fare (carry on only; bags and seats extra).")
    return out
