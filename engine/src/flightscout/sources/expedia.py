"""Expedia Group flight search (Expedia, Orbitz, Travelocity) through the
GraphQL query their own results page runs (FlightsSearchResultsLoadedQuery,
a persisted query on /graphql).

Plain HTTP with Chrome TLS impersonation works: one GET of the site's own
search page (sets the anonymous visitor cookies, DUAID) and one POST to
/graphql, sorted by price with progressive rendering off so the answer is
complete. About 2 to 5 seconds per route. When the persisted query hash
goes stale (Expedia deploys), or Akamai refuses the plain client, the same
search runs in the shared headless Chrome (_browser.py) and we read the
response the page itself fetches.

The answer is a UI tree, not a flight list: we read each offer's segments
(airports, local times, marketing flight number) and its fare cards, whose
second price row states the exact total for all travelers ("$248.40 one way
for 1 traveler"). Round trips: the list is outbound flights, each priced as
the cheapest round trip with it (return picked on the site), so those
Itineraries are ``return_pending`` like Google's.

Prices are in the site's currency (Expedia by domain, see _EXPEDIA; Orbitz and
Travelocity are US sites in USD). English locales only (we read texts)."""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from datetime import date, datetime

from curl_cffi import requests as cr

from .. import cache
from ..models import Fare, Itinerary, Offer, SearchQuery, Segment, Slice
from . import _browser

log = logging.getLogger(__name__)

# Currency -> Expedia site that sells in it (English locales only).
_EXPEDIA = {"USD": "www.expedia.com", "GBP": "www.expedia.co.uk", "CAD": "www.expedia.ca",
            "AUD": "www.expedia.com.au", "EUR": "www.expedia.ie", "INR": "www.expedia.co.in",
            "SGD": "www.expedia.com.sg", "NZD": "www.expedia.co.nz"}
BRANDS = {"expedia": "Expedia", "orbitz": "Orbitz", "travelocity": "Travelocity"}
_US = {"orbitz": "www.orbitz.com", "travelocity": "www.travelocity.com"}
# Default page context when the site's cookies don't tell (tpid = siteId).
_SITE_IDS = {"www.expedia.com": 1, "www.orbitz.com": 70201, "www.travelocity.com": 80001}

OPERATION = "FlightsSearchResultsLoadedQuery"
# Apollo persisted query id of the results query in Expedia's own JS (not a
# credential). Refreshed at runtime from the browser when it goes stale.
_hash = {"v": "a264408c24658390ada64ebe2e434fbafecc4543c5727fbeef4ec10ed1c173e1"}
_CABIN = {"economy": "COACH", "premium": "PREMIUM_ECONOMY", "business": "BUSINESS", "first": "FIRST"}
_local = threading.local()
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


def domain(brand: str, currency: str = "USD") -> str:
    if brand == "expedia":
        return _EXPEDIA.get(currency.upper(), "www.expedia.com")
    return _US[brand]


def deeplink(dom: str, origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1,
             cabin: str = "economy") -> str:
    """The site's own results page for the search."""
    def leg(n, a, b, d):
        return f"leg{n}=from:{a},to:{b},departure:{d.month}/{d.day}/{d.year}TANYT"

    legs = leg(1, origin, dest, dep) + (("&" + leg(2, dest, origin, ret)) if ret else "")
    return (f"https://{dom}/Flights-Search?trip={'roundtrip' if ret else 'oneway'}&{legs}"
            f"&passengers=adults:{adults}&mode=search&options=cabinclass:{cabin}&sortOrder=INCREASING&sortType=PRICE")


# ---------------------------------------------------------------- parsing

def _amount(text: str) -> float | None:
    """'$1,063.20 roundtrip for 2 travelers' -> 1063.2 (first number)."""
    m = re.search(r"\d[\d,.  ]*", text or "")
    if not m:
        return None
    s = m.group(0).strip().replace(" ", "").replace(" ", "")
    if re.search(r"[.,]\d{2}$", s):  # decimal part
        s = re.sub(r"[.,]", "", s[:-3]) + "." + s[-2:]
    else:
        s = re.sub(r"[.,]", "", s)
    return float(s)


def _minutes(text: str) -> int | None:
    h = re.search(r"(\d+)\s*h", text or "")
    m = re.search(r"(\d+)\s*m", text or "")
    if not h and not m:
        return None
    return int(h.group(1) if h else 0) * 60 + int(m.group(1) if m else 0)


def _when(parts: list[dict], near: date) -> datetime:
    """[{'text': '7:03am'}, {'text': 'PST'}, {'text': 'Fri, Nov 6'}] -> datetime.
    The year is not shown: the one that puts the date closest to ``near``."""
    texts = [p.get("text") or "" for p in parts]
    tm = next(m for t in texts if (m := re.fullmatch(r"(\d{1,2}):(\d{2})\s*([ap]m)?", t.strip(), re.I)))
    h, mi = int(tm.group(1)), int(tm.group(2))
    if tm.group(3):
        h = h % 12 + (12 if tm.group(3).lower() == "pm" else 0)
    day = near
    for t in texts:
        mon = next((v for k, v in _MONTHS.items() if re.search(rf"\b{k}", t, re.I)), None)
        dn = re.search(r"\b(\d{1,2})\b", t)
        if mon and dn:
            cands = [date(y, mon, int(dn.group(1))) for y in (near.year - 1, near.year, near.year + 1)]
            day = min(cands, key=lambda c: abs((c - near).days))
            break
    return datetime(day.year, day.month, day.day, h, mi)


def _find(x, key: str):
    """Every value under ``key`` anywhere in a JSON tree."""
    if isinstance(x, dict):
        for k, v in x.items():
            if k == key:
                yield v
            yield from _find(v, key)
    elif isinstance(x, list):
        for v in x:
            yield from _find(v, key)


def _segments(journey: dict, near: date) -> list[dict]:
    segs = []
    for sections in _find(journey, "journeySections"):
        for sec in sections or []:
            for ci in sec.get("journeyConnectionInformation") or []:
                c = ci.get("flightsConnection")
                if not c:
                    continue
                texts = (c.get("airlineDetails") or {}).get("text") or []
                items = texts[0].get("items") if texts else []
                code = next((i["text"] for i in items or [] if re.fullmatch(r"[A-Z0-9]{2}\d{1,4}", i.get("text") or "")),
                            None)
                if not code:
                    m = re.search(r"\b([A-Z0-9]{2})(\d{1,4})\b", (texts[0].get("completeText") if texts else "") or "")
                    code = m.group(0) if m else None
                ap = [re.search(r"\(([A-Z]{3})\)\s*$", (c.get(k) or {}).get("subtitle") or "")
                      for k in ("connectionDeparture", "connectionArrival")]
                if not code or not all(ap):
                    raise ValueError(f"expedia: unreadable segment {json.dumps(c)[:200]}")
                segs.append({
                    "origin": ap[0].group(1), "destination": ap[1].group(1),
                    "departure": _when(c["connectionDeparture"]["journeyDateTime"], near).isoformat(),
                    "arrival": _when(c["connectionArrival"]["journeyDateTime"], near).isoformat(),
                    "carrier": code[:2], "number": code[2:],
                    "carrier_name": items[0].get("text") if items else None,
                    "duration": _minutes((c.get("duration") or "").split(":")[-1]),
                    "aircraft": c.get("aircraftModel"),
                })
        if segs:  # the first journeySections list is the flight details
            break
    return segs


def _journey_minutes(journey: dict) -> int | None:
    """'12:40pm - 8:59pm (5h 19m, nonstop)' -> 319."""
    for t in _find(journey, "text"):
        if isinstance(t, str) and (m := re.search(r"\((\d+h(?:\s*\d+m)?|\d+m),", t)):
            return _minutes(m.group(1))
    return None


def _fares(journey: dict) -> list[dict]:
    """Every fare card: name and exact total for all travelers (without
    Expedia's optional Price Drop Protection add on)."""
    out = []
    for fares in _find(journey, "fares"):
        for f in fares or []:
            if not isinstance(f, dict) or "heading" not in f:
                continue
            pricing = ((f.get("heading") or {}).get("farePricing") or [None])[0]
            rows = (pricing or {}).get("priceDisplay", {}).get("rows") or []
            total = None
            if len(rows) > 1:
                el = rows[1]["elements"][0]
                total = _amount(((el.get("value") or el.get("price") or {}).get("text")) or "")
            name = ((f.get("fareDetails") or [{}])[0]).get("text")
            if total:
                out.append({"name": name, "total": total})
        if out:
            break
    return out


def parse(data: dict | list, dep: date) -> list[dict]:
    """GraphQL answer -> journeys: {"segments", "duration", "total", "fares"}.
    ``dep`` anchors the dates (the UI shows 'Fri, Nov 6', no year)."""
    if isinstance(data, list):
        data = data[0]
    fs = ((data.get("data") or {}).get("flightsSearch") or {})
    out, seen = [], set()
    for o in (fs.get("listingResult") or {}).get("listings") or []:
        if o.get("__typename") != "FlightsStandardOffer" or not o.get("journeys"):
            continue
        j = o["journeys"][0]
        try:
            segs = _segments(j, dep)
        except (ValueError, StopIteration, KeyError) as e:
            log.debug("expedia: skip offer: %s", e)
            continue
        fares = _fares(j)
        key = tuple(s["carrier"] + s["number"] + s["departure"] for s in segs)
        if not segs or not fares or key in seen:
            continue
        seen.add(key)
        out.append({"segments": segs, "duration": _journey_minutes(j), "fares": fares,
                    "total": min(f["total"] for f in fares)})
    return out


# ---------------------------------------------------------------- fetching

def _session(dom: str) -> cr.Session:
    """One per site and thread: the brands share cookie names (tpid, DUAID)."""
    if not hasattr(_local, "s"):
        _local.s = {}
    if dom not in _local.s:
        _local.s[dom] = cr.Session(impersonate="chrome")
    return _local.s[dom]


def _payload(ctx: dict, legs: list[tuple[str, str, date]], adults: int, cabin: str) -> list[dict]:
    return [{
        "operationName": OPERATION,
        "variables": {
            "faresSeparationType": "BASE_AND_UPSELL", "searchFilterValuesList": [],
            "flightsSearchContext": {"tripType": "ROUND_TRIP" if len(legs) == 2 else "ONE_WAY",
                                     "previousOriginalBookingId": None, "journeysContinuationId": None,
                                     "hasCreditRedemptionIntent": None, "originalBookingId": None,
                                     "searchId": str(uuid.uuid4())},
            "journeyCriteria": [{"departureDate": {"month": d.month, "day": d.day, "year": d.year},
                                 "origin": a, "destination": b, "originAirportLocationType": "UNSPECIFIED",
                                 "destinationAirportLocationType": "UNSPECIFIED"} for a, b, d in legs],
            "searchPreferences": {"cabinClass": _CABIN.get(cabin, "COACH")},
            "sortOption": {"sortOrder": "INCREASING", "sortType": "PRICE"},
            "travelerDetails": [{"travelerType": "ADULT", "count": adults}],
            "searchPagination": None, "progressiveRenderingInput": {"enabled": False},
            "flightsSearchComponentCriteria": {"queryParams": []}, "shoppingContext": None,
            "virtualAgentContext": None,
            "context": {"siteId": ctx["site"], "locale": ctx["locale"], "eapid": ctx["eapid"], "tpid": ctx["site"],
                        "currency": ctx["currency"], "device": {"type": "DESKTOP"},
                        "identity": {"duaid": ctx["duaid"], "authState": "ANONYMOUS"},
                        "privacyTrackingState": "CAN_TRACK"},
            "queryState": "LOADED"},
        "extensions": {"persistedQuery": {"version": 1, "sha256Hash": _hash["v"]}},
    }]


def _http(dom: str, page: str, legs, adults: int, cabin: str) -> tuple[dict, str]:
    s = _session(dom)
    r = s.get(page, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"search page HTTP {r.status_code}")
    tpid = (s.cookies.get("tpid") or "").split(",")[-1]
    m = re.search(r'\\?"locale\\?":\\?"([a-z]{2}_[A-Z]{2})', r.text)
    ci = re.search(r"(flights-shopping-pwa,[a-z]+,[a-z]+)", r.text)
    ctx = {"site": int(tpid) if tpid.isdigit() else _SITE_IDS.get(dom, 1),
           "eapid": int(s.cookies.get("iEAPID") or 0) if (s.cookies.get("iEAPID") or "0").isdigit() else 0,
           "locale": m.group(1) if m else "en_US", "currency": s.cookies.get("currency") or "USD",
           "duaid": s.cookies.get("DUAID") or str(uuid.uuid4())}
    r = s.post(f"https://{dom}/graphql", json=_payload(ctx, legs, adults, cabin), timeout=60,
               headers={"Origin": f"https://{dom}", "Referer": page, "Content-Type": "application/json",
                        "client-info": ci.group(1) if ci else "flights-shopping-pwa,latest,external"})
    if r.status_code != 200:
        raise RuntimeError(f"graphql HTTP {r.status_code}")
    d = r.json()
    d = d[0] if isinstance(d, list) else d
    if d.get("errors") and not (d.get("data") or {}).get("flightsSearch"):
        raise RuntimeError("graphql: " + str(d["errors"][0].get("message"))[:150])
    return d, ctx["currency"]


def _via_browser(dom: str, page: str) -> tuple[dict, str]:
    """Load the results page in headless Chrome and read the loaded query
    the page runs itself (also learns the current persisted query hash)."""
    def job(pg) -> tuple[str, str]:
        got: list[tuple[str, str]] = []

        def on(r):
            if "/graphql" not in r.url:
                return
            # some requests on the page carry binary (compressed) bodies
            post = (r.request.post_data_buffer or b"").decode("utf-8", "ignore")
            if "/graphql" in r.url and OPERATION in post and '"LOADED"' in post and r.ok:
                try:
                    got.append((post, r.text()))
                except Exception as e:
                    log.debug("expedia body: %s", e)

        pg.on("response", on)
        try:
            pg.goto(page, wait_until="commit", timeout=45000)
            end = time.time() + 45
            while not got and time.time() < end:
                pg.wait_for_timeout(300)
            cur = pg.evaluate("document.cookie.match(/currency=([A-Z]{3})/)?.[1] || ''")
        finally:
            pg.remove_listener("response", on)
        return (got[-1] if got else ("", "")) + (cur,)

    post, txt, cur = _browser.run(job, f"expedia:{dom}", timeout=120)
    if not txt:
        raise RuntimeError("expedia: the results page sent no flight list (headless Chrome)")
    try:
        _hash["v"] = json.loads(post)[0]["extensions"]["persistedQuery"]["sha256Hash"]
    except Exception:
        pass
    d = json.loads(txt)
    return (d[0] if isinstance(d, list) else d), cur or "USD"


def fetch(brand: str, origin: str, dest: str, dep: date, ret: date | None, adults: int,
          cabin: str, currency: str) -> tuple[list[dict], str, str]:
    """-> (journeys, currency, deeplink), cached."""
    dom = domain(brand, currency)
    page = deeplink(dom, origin, dest, dep, ret, adults, cabin)
    key = f"expedia:{dom}:{origin}:{dest}:{dep}:{ret}:{adults}:{cabin}"
    if (hit := cache.get(key)) is not None:
        return hit["journeys"], hit["currency"], page
    legs = [(origin, dest, dep)] + ([(dest, origin, ret)] if ret else [])
    try:
        data, cur = _http(dom, page, legs, adults, cabin)
    except Exception as e:
        if not _browser.available():
            raise RuntimeError(f"{brand}: {e}") from e
        log.info("%s: plain HTTP failed (%s), using the browser", brand, e)
        data, cur = _via_browser(dom, page)
    journeys = parse(data, dep)
    cache.put(key, {"journeys": journeys, "currency": cur})
    return journeys, cur, page


def _slice(j: dict) -> Slice:
    segs = [Segment(origin=s["origin"], destination=s["destination"],
                    departure=datetime.fromisoformat(s["departure"]), arrival=datetime.fromisoformat(s["arrival"]),
                    carrier=s["carrier"], carrier_name=s.get("carrier_name"), flight_number=s["number"],
                    duration_min=s.get("duration"), aircraft=s.get("aircraft")) for s in j["segments"]]
    dur = j.get("duration") or int((segs[-1].arrival - segs[0].departure).total_seconds() // 60)
    return Slice(segments=segs, duration_min=max(dur, 1))


def itineraries(brand: str, q: SearchQuery, journeys: list[dict], currency: str, url: str) -> list[Itinerary]:
    name = BRANDS[brand]
    out = []
    for j in journeys:
        sl = _slice(j)
        if sl.origin not in q.origins or sl.destination not in q.destinations:
            continue  # the site mixes in nearby airports
        if q.max_stops is not None and sl.stops > q.max_stops:
            continue
        warn = [f"Sold by {name} (online travel agency)."]
        if q.return_date:
            warn.append(f"Round trip price with {name}'s cheapest return for this outbound; pick the return on {name}.")
        out.append(Itinerary(
            source=brand, price=round(j["total"], 2), currency=currency, slices=[sl], booking_url=url,
            seller=name, seller_kind="ota", return_pending=bool(q.return_date), warnings=warn,
            offers=[Offer(seller=name, is_airline=False,
                          fares=[Fare(name=f["name"], price=f["total"]) for f in j["fares"]])],
        ))
    return out


def search_brand(brand: str, q: SearchQuery) -> list[Itinerary]:
    out: list[Itinerary] = []
    errors = []
    for o in q.origins[:2]:
        for d in q.destinations[:2]:
            if o == d:
                continue
            try:
                js, cur, url = fetch(brand, o, d, q.departure, q.return_date, q.adults, q.cabin, q.currency)
            except Exception as e:
                errors.append(str(e))
                continue
            out += itineraries(brand, q, js, cur, url)
    if errors and not out:
        raise RuntimeError(errors[0][:300])
    return out


def search(q: SearchQuery) -> list[Itinerary]:
    return search_brand("expedia", q)


def search_orbitz(q: SearchQuery) -> list[Itinerary]:
    return search_brand("orbitz", q)


def search_travelocity(q: SearchQuery) -> list[Itinerary]:
    return search_brand("travelocity", q)
