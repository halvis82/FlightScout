"""flydubai (FZ) direct from flydubai.com through the shared headless Chrome
(see _browser.py). Its booking app (flights2.flydubai.com) sits behind Akamai
Bot Manager: plain HTTP clients get "Access Denied" on the flight API.

We open the site's own results deeplink
(/en/results/ow/a1c0i0/DXB_KTM/20261020?...) and capture the JSON the app
posts to /api/flights/1: every flight with every fare family (LITE, VALUE,
FLEX, Business) and its price incl. taxes, in the point of sale currency
(AED from the /en site). Round trips are priced as two one ways (flydubai
prices each direction on its own).

Before opening a browser we ask flydubai's public schedule endpoint
(www.flydubai.com/api/Calendar, plain JSON, no key) whether the route flies
that day at all, so empty dates cost one small HTTP call.

Caveat: Akamai lets the first one or two flight searches of a browser session
through and then answers 403 for a while. The source raises an error then
(search() reports it per source) instead of returning anything guessed."""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta

from curl_cffi import requests as cr

from .. import cache, fx
from ..models import DatePrice, Itinerary, SearchQuery
from . import _browser
from ._airline import combine, countries

log = logging.getLogger(__name__)
SITE = "https://flights2.flydubai.com"
AIRPORTS_URL = f"{SITE}/tridionfeed/en/include/json/airportlist.json"
CALENDAR_URL = "https://www.flydubai.com/api/Calendar/{o}/{d}?fromDate={day}&isOriginMetro=false&isDestMetro=false"
NAMES = {"FZ": "flydubai", "EK": "Emirates"}
# Countries flydubai itself flies to (every ticket connects in Dubai). The
# airport list also carries Emirates codeshare points (Americas, Oceania),
# which we leave to other sources.
COUNTRIES = {
    "AE", "SA", "OM", "KW", "BH", "QA", "IQ", "IR", "JO", "LB", "SY", "EG", "SD", "SS", "ET", "ER", "SO", "DJ",
    "KE", "TZ", "UG", "CD", "ZM", "ZW", "MZ", "TR", "GE", "AM", "AZ", "KZ", "KG", "UZ", "TJ", "TM", "AF", "PK",
    "IN", "NP", "BD", "LK", "MV", "TH", "MY", "RU", "PL", "CZ", "SK", "RO", "BG", "RS", "BA", "MK", "AL", "ME",
    "HR", "SI", "HU", "AT", "IT", "GR", "CY", "FI", "ES", "MT", "LV", "EE", "LT", "MD", "UA", "DE", "BE", "FR",
    "DK", "NO", "SE", "CH", "PT", "GB",
}
_CABIN = {"economy": "Economy", "premium": "Economy", "business": "Business", "first": "Business"}


def available() -> bool:
    return _browser.available()


def network() -> set[str]:
    """Airports on sale at flydubai.com (its own network plus Emirates
    codeshare points), from the booking app's public airport list."""
    hit = cache.get("flydubai:airports", ttl=7 * 86400)
    if hit is None:
        r = cr.get(AIRPORTS_URL, impersonate="chrome", timeout=30)
        r.raise_for_status()
        hit = sorted({a["key"] for c in r.json()["category"] for a in c["item"] if len(a.get("key", "")) == 3})
        cache.put("flydubai:airports", hit)
    return set(hit)


def relevant(origins: list[str], destinations: list[str]) -> bool:
    if not available():
        return False
    try:
        net = network()
    except Exception:
        return False
    o = [c for c in origins if c in net]
    d = [c for c in destinations if c in net]
    return bool(o and d) and (countries(o) | countries(d)) <= COUNTRIES


def flies(origin: str, dest: str, day: date) -> bool:
    """Does flydubai sell origin -> dest on ``day``? (schedule only, no prices)"""
    key = f"flydubai:sched:{origin}:{dest}:{day:%Y-%m}"
    hit = cache.get(key, ttl=12 * 3600)
    if hit is None:
        try:
            r = cr.get(CALENDAR_URL.format(o=origin, d=dest, day=day.replace(day=1).isoformat()),
                       impersonate="chrome", timeout=30, headers={"Accept": "application/json"})
            r.raise_for_status()
            hit = [d[:10] for rt in r.json().get("routes") or [] for d in rt.get("flightSchedules") or []]
        except Exception as e:  # unknown: let the live search decide
            log.debug("flydubai schedule failed: %s", e)
            return True
        cache.put(key, hit)
    return day.isoformat() in hit


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1,
             cabin: str = "economy") -> str:
    kind, dates = ("rt", f"{dep:%Y%m%d}_{ret:%Y%m%d}") if ret else ("ow", f"{dep:%Y%m%d}")
    return (f"{SITE}/en/results/{kind}/a{adults}c0i0/{origin}_{dest}/{dates}"
            f"?cabinClass={_CABIN.get(cabin, 'Economy')}&isOriginMetro=false&isDestMetro=false&pm=cash")


def _num(s) -> float:
    return float(str(s).replace(",", ""))


def _mins(s: str | None) -> int | None:
    if not s or ":" not in s:
        return None
    h, m = s.split(":")[:2]
    return int(h) * 60 + int(m)


def parse(data: dict, adults: int = 1, cabin: str = "economy") -> tuple[list[dict], str | None]:
    """flights/1 JSON -> (journeys, currency). Each journey keeps its cheapest
    available fare family in the asked cabin (economy families for economy
    and premium, Business for business and first)."""
    want_business = cabin in ("business", "first")
    out, currency = [], None
    for seg in data.get("segments") or []:
        if (seg.get("direction") or "outBound").lower() != "outbound":
            continue
        for f in seg.get("flights") or []:
            if not f.get("isAvailabile", True):
                continue
            best = None
            for ft in f.get("fareTypes") or []:
                fare = ft.get("fare")
                if not fare or ft.get("isSoldOut"):
                    continue
                if ((ft.get("cabin") or "").lower() == "business") != want_business:
                    continue
                adult = ((ft.get("fareInformation") or {}).get("adultFares") or [{}])[0]
                per = _num(adult.get("adultFarePerPax") or fare["totalFare"])
                if best is None or per < best[0]:
                    best = (per, fare.get("currencyCode"), ft.get("fareTypeName"), ft.get("seatsLeft"))
            if not best or not f.get("legs"):
                continue
            segs = [{"origin": lg["origin"], "destination": lg["destination"],
                     "departure": lg["departureDate"], "arrival": lg["arrivalDate"],
                     "carrier": lg.get("marketingCarrier") or lg.get("operatingCarrier") or "FZ",
                     "number": lg.get("marketingFlightNum") or lg.get("flightNumber"),
                     "duration": _mins(lg.get("flightDuration")), "aircraft": lg.get("equipmentType")}
                    for lg in f["legs"]]
            out.append({"segments": segs, "total": round(best[0] * adults, 2), "fare": best[2],
                        "seats": best[3], "duration": _mins(f.get("totalDuration"))})
            currency = best[1] or seg.get("currencyCode")
    return out, currency


def _load(url: str, want: str) -> dict[str, tuple[int, str]]:
    """Open a results deeplink and collect the app's own /api/flights/1
    (availability) and /api/flights/7 (7 day lowest fare strip) responses:
    {"1": (status, body), "7": (status, body)}. Waits for ``want``."""
    def job(page) -> dict:
        got: dict[str, tuple[int, str]] = {}

        def on(r):
            if "/api/flights/" in r.url and r.request.method == "POST":
                n = r.url.rsplit("/", 1)[-1].split("?")[0]
                try:
                    got[n] = (r.status, r.text() if r.ok else "")
                except Exception:
                    got[n] = (r.status, "")

        page.on("response", on)
        try:
            page.goto(url, wait_until="commit", timeout=45000)
            for _ in range(150):  # up to 30 s
                if want in got:
                    break
                page.wait_for_timeout(200)
            if want in got:
                page.wait_for_timeout(1500)  # the sibling call is usually in flight
        finally:
            page.remove_listener("response", on)
        return got

    return _browser.run(job, "flydubai", timeout=120)


def _json(got: dict, n: str) -> dict:
    status, txt = got.get(n, (0, ""))
    if status == 403:
        raise RuntimeError("flydubai: Akamai refused the flight search (403), try again in a few minutes")
    if not txt:
        raise RuntimeError(f"flydubai: no /api/flights/{n} response (status {status})")
    return json.loads(txt)


def _fetch(url: str) -> dict:
    got = _load(url, "1")
    if got.get("7", (0, ""))[1]:  # free calendar data: keep it for dates()
        try:
            _store_strip(json.loads(got["7"][1]))
        except ValueError:
            pass
    return _json(got, "1")


def parse_strip(data: dict) -> list[tuple[str, str, date, float, str]]:
    """flights/7 JSON -> [(origin, dest, day, lowest adult fare incl. taxes, currency)]."""
    out = []
    for seg in data.get("segments") or []:
        if seg.get("isSoldOut") or not seg.get("lowestAdultFarePerPax"):
            continue
        out.append((seg["origin"], seg["dest"], date.fromisoformat(seg["departureDate"][:10]),
                    _num(seg["lowestAdultFarePerPax"]), seg.get("currencyCode") or "AED"))
    return out


def _store_strip(data: dict) -> None:
    for o, d, day, price, cur in parse_strip(data):
        cache.put(f"flydubai:day:{o}:{d}:{day}", [price, cur])


def _bound(o: str, d: str, day: date, adults: int, cabin: str) -> tuple[list[dict], str | None]:
    key = f"flydubai:{o}:{d}:{day}:{adults}:{cabin}"
    if (hit := cache.get(key)) is None:
        if not flies(o, d, day):
            return [], None
        hit = _fetch(deeplink(o, d, day, adults=adults, cabin=cabin))
        cache.put(key, hit)
    return parse(hit, adults, cabin)


def search(q: SearchQuery) -> list[Itinerary]:
    if not relevant(q.origins, q.destinations):
        return []
    net = network()
    out: list[Itinerary] = []
    for o in [c for c in q.origins if c in net][:2]:
        for d in [c for c in q.destinations if c in net][:2]:
            if o == d:
                continue
            outs, cur = _bound(o, d, q.departure, q.adults, q.cabin)
            backs = None
            if q.return_date:
                if not outs:
                    continue
                backs, _ = _bound(d, o, q.return_date, q.adults, q.cabin)
                if not backs:
                    continue
            if not outs:
                continue
            fares = sorted({x["fare"] for x in outs if x.get("fare")})
            out += combine(q, "flydubai", "flydubai", outs, backs, cur or "AED",
                           deeplink(o, d, q.departure, q.return_date, q.adults, q.cabin), NAMES,
                           note=f"flydubai cheapest fare family ({'/'.join(fares) or 'LITE'}; LITE has no checked bag).")
    return out


def dates(origin: str, dest: str, start: date, end: date, currency: str = "USD",
          cabin: str = "economy") -> list[DatePrice]:
    """Cheapest economy one way fare per day (adult, incl. taxes) from the
    7 day fare strip the results page loads (/api/flights/7). That call is
    not blocked the way the flight list is. One page load per week, at most
    five, and only for weeks the schedule says flydubai flies."""
    out: list[DatePrice] = []
    found: dict[date, tuple[float, str]] = {}
    day, loads = start, 0
    while day <= end:
        need = [day + timedelta(days=i) for i in range(7) if day + timedelta(days=i) <= end]
        for x in need:
            if (hit := cache.get(f"flydubai:day:{origin}:{dest}:{x}", ttl=6 * 3600)):
                found[x] = tuple(hit)
        if loads < 5 and not any(x in found for x in need) and any(flies(origin, dest, x) for x in need):
            strip = _json(_load(deeplink(origin, dest, max(day + timedelta(days=3), date.today())), "7"), "7")
            _store_strip(strip)
            loads += 1
            for o, d, x, price, cur in parse_strip(strip):
                if o == origin and d == dest:
                    found[x] = (price, cur)
        day += timedelta(days=7)
    for x in sorted(found):
        if not start <= x <= end:
            continue
        price, cur = found[x]
        if currency.upper() != cur:
            price, cur = fx.convert(price, cur, currency), currency.upper()
        out.append(DatePrice(origin=origin, destination=dest, departure=x, price=round(price, 2),
                             currency=cur, source="flydubai", booking_url=deeplink(origin, dest, x)))
    return out
