"""Vueling (VY) direct from vueling.com's own booking backend (ams.vueling.com,
a Navitaire dotREZ wrapper with a GraphQL availability endpoint).

No secret: the booking app (tickets.vueling.com) logs every visitor in
anonymously with POST /asm/v1/Auth {"profileId": ...}, where profileId is a
public client id shipped in the app's JS bundle. We read it from the bundle at
runtime (cached a week) and get a 20 minute bearer token from it. Plain HTTP
with Chrome TLS (curl_cffi) is enough, no browser needed. One GraphQL call per
direction, under a second each (the first search of the week also reads the
bundle, which can take 20 seconds as Akamai is slow with the HTML page).

Prices: the cheapest fare of each flight, "Basic" (fare + zero priced VYBA
bundle), is exactly the "SELECT FLIGHT FOR 60 EUR" / "Ticket price per person
€59,99" on the flight selection page. amsFareAmount is per adult, taxes
included. Round trips are priced as two one ways (same as the site's own
per direction selection). Times in the response carry a bogus "Z": they are
local wall clock times; the legs carry the real UTC times, used for durations."""

from __future__ import annotations

import re
import threading
import time
from datetime import date, datetime

from curl_cffi import requests as cr

from .. import cache
from ..models import Itinerary, SearchQuery
from ._airline import combine

API = "https://ams.vueling.com"
APP = "https://tickets.vueling.com"
NAMES = {"VY": "Vueling"}
_H = {"Origin": APP, "Referer": APP + "/", "Accept": "application/json, text/plain, */*"}
_lock = threading.Lock()
_session: cr.Session | None = None
_token: tuple[str, float] | None = None

# Vueling stations (tickets.vueling.com stations list, September 2026).
STATIONS = {
    "ACE", "AGA", "AGP", "ALC", "ALG", "AMS", "ARN", "ATH", "BCN", "BER", "BHX", "BIO", "BJL", "BLQ", "BOD", "BRI",
    "BRU", "BSL", "BUD", "CAG", "CAI", "CDG", "CDT", "CFU", "CMN", "CPH", "CTA", "CWL", "DBV", "DSS", "DUB", "DUS",
    "EAS", "EDI", "ESU", "FAO", "FCO", "FEZ", "FLR", "FNC", "FRA", "FUE", "GLA", "GOA", "GRX", "GVA", "HAJ", "HAM",
    "HER", "IBZ", "ILD", "IST", "IVL", "JMK", "JTR", "KEF", "LCG", "LCY", "LEI", "LEN", "LEU", "LGW", "LHR", "LIN",
    "LIS", "LJU", "LLA", "LPA", "LYS", "MAD", "MAH", "MAN", "MLA", "MLN", "MRS", "MUC", "MXP", "NAP", "NCE", "NDR",
    "NTE", "NUE", "ODB", "OLB", "OPO", "ORN", "ORY", "OSL", "OTP", "OVD", "PMI", "PMO", "PNA", "PRG", "QSR", "RAK",
    "REU", "RJL", "RVN", "SCQ", "SDR", "SID", "SPC", "SPU", "STN", "STR", "SVQ", "SXB", "TFN", "TFS", "TLS", "TLV",
    "TNG", "TOS", "TRN", "TUN", "VCE", "VGO", "VIE", "VLC", "VLL", "XRY", "ZAG", "ZAZ", "ZRH",
}

# The booking app's own availability query, trimmed to the fields we read.
QUERY = """query GetAvy($requestAVY:AvailabilityRequestGraphQLInput!){ amsAvy (amsAvailabilityRequest : $requestAVY) {
 currencyCode,
 trips { trips { journeysAvailableByMarket { key, value {
   segments { identifier { carrierCode, identifier }, designator { arrival, departure, destination, origin },
     segmentDuration, legs { legInfo { operatingCarrier, arrivalTimeUtc, departureTimeUtc } } },
   designator { arrival, departure, destination, origin },
   fares { fareAvailabilityKey, details { serviceBundleSetCode, availableCount } },
   flightType, duration } } } },
 faresAvailable { value { fares { productClass, classOfService, passengerFares { amsFareAmount } },
   fareAvailabilityKey } }
} }"""


def relevant(origins: list[str], destinations: list[str]) -> bool:
    return any(c in STATIONS for c in origins) and any(c in STATIONS for c in destinations)


def _s() -> cr.Session:
    global _session
    if _session is None:
        _session = cr.Session(impersonate="chrome")
    return _session


def _profile_id() -> str:
    """The public anonymous client id from the booking app's JS bundle."""
    pid = cache.get("vueling:profile", ttl=7 * 86400)
    if pid:
        return pid
    html = _s().get(APP + "/", timeout=60).text
    main = re.search(r"(main-[A-Z0-9]+\.js)", html)
    if not main:
        raise RuntimeError("vueling: booking app bundle not found")
    js = _s().get(f"{APP}/app/{main.group(1)}", timeout=60).text
    for chunk in [main.group(1)] + list(dict.fromkeys(re.findall(r'from"\./(chunk-[A-Z0-9]+\.js)"', js)))[:6]:
        src = js if chunk == main.group(1) else _s().get(f"{APP}/app/{chunk}", timeout=60).text
        if m := re.search(r'profileId:"([0-9a-f-]{36})"', src):
            cache.put("vueling:profile", m.group(1))
            return m.group(1)
    raise RuntimeError("vueling: public profile id not found in the booking app")


def _auth() -> str:
    global _token
    if _token and time.time() - _token[1] < 15 * 60:
        return _token[0]
    r = _s().post(f"{API}/asm/v1/Auth", json={"profileId": _profile_id()}, headers=_H, timeout=30)
    if r.status_code in (400, 401, 403):
        cache.put("vueling:profile", "")  # rotated id: read the bundle again next time
    r.raise_for_status()
    _token = (r.json()["accessToken"], time.time())
    return _token[0]


def markets(origin: str) -> set[str] | None:
    """Destinations Vueling sells from ``origin`` (direct or connecting)."""
    key = f"vueling:markets:{origin}"
    if (hit := cache.get(key, ttl=3 * 86400)) is not None:
        return set(hit)
    try:
        with _lock:
            r = _s().get(f"{API}/res/v1/Markets/ByOrigin/{origin}",
                          headers={**_H, "Authorization": "Bearer " + _auth()}, timeout=30)
        r.raise_for_status()
        out = sorted({m["toCode"] for m in r.json()})
    except Exception:
        return None  # unknown: let the availability call decide
    cache.put(key, out)
    return set(out)


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1,
             currency: str = "EUR") -> str:
    u = f"{APP}/booking?o={origin}&d={dest}&dd={dep.isoformat()}&adt={adults}&chd=0&inf=0&c=en-GB&cur={currency}"
    if ret:
        u += f"&rd={ret.isoformat()}"
    return u


def _local(s: str) -> str:
    return s.replace(".000Z", "").rstrip("Z")


def _utc(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def parse(data: dict, adults: int = 1) -> tuple[list[dict], str]:
    """GraphQL amsAvy response -> (journeys, currency), cheapest fare per
    journey (the Basic fare), total for ``adults``."""
    d = data["data"]["amsAvy"]
    cur = d.get("currencyCode") or "EUR"
    fares = {}
    for x in d.get("faresAvailable") or []:
        v = x.get("value") or {}
        amts = [pf["amsFareAmount"] for f in v.get("fares") or [] for pf in f.get("passengerFares") or []
                if pf.get("amsFareAmount") is not None]
        if amts:
            fares[v["fareAvailabilityKey"]] = (amts[0], (v.get("fares") or [{}])[0].get("productClass"))
    out = []
    for t in d.get("trips") or []:
        for tt in t.get("trips") or []:
            for m in tt.get("journeysAvailableByMarket") or []:
                for j in m.get("value") or []:
                    best = None
                    for f in j.get("fares") or []:
                        p = fares.get(f["fareAvailabilityKey"])
                        if p and (best is None or p[0] < best[0]):
                            seats = min((x.get("availableCount") or 99 for x in f.get("details") or []), default=None)
                            best = (p[0], p[1], seats)
                    if not best:
                        continue
                    segs, legs = [], []
                    for s in j["segments"]:
                        legs += s.get("legs") or []
                        op = next((lg["legInfo"].get("operatingCarrier") for lg in s.get("legs") or []
                                   if (lg.get("legInfo") or {}).get("operatingCarrier")), None)
                        segs.append({
                            "origin": s["designator"]["origin"], "destination": s["designator"]["destination"],
                            "departure": _local(s["designator"]["departure"]),
                            "arrival": _local(s["designator"]["arrival"]),
                            "carrier": op or s["identifier"]["carrierCode"],
                            "number": s["identifier"]["identifier"].strip(), "duration": s.get("segmentDuration"),
                        })
                    dur = j.get("duration")
                    li = [lg.get("legInfo") or {} for lg in legs]
                    if li and li[0].get("departureTimeUtc") and li[-1].get("arrivalTimeUtc"):
                        dur = int((_utc(li[-1]["arrivalTimeUtc"]) - _utc(li[0]["departureTimeUtc"])).total_seconds()
                                  // 60)
                    out.append({"segments": segs, "total": round(best[0] * adults, 2), "fare": best[1],
                                "seats": best[2], "duration": dur})
    return out, cur


def _request(o: str, d: str, day: date, adults: int, cur: str) -> dict:
    return {"query": QUERY, "variables": {"requestAVY": {"request": {
        "criteria": [{"origin": o, "destination": d, "date": f"{day.isoformat()}T00:00:00.000Z"}],
        "cultureCode": "en-GB", "currencyCode": cur, "flightType": "ALL", "itineraryType": "ONE_WAY",
        "maxConnections": 10, "passengers": [{"count": adults, "type": "Adult"}], "serviceCode": "Search1Day",
        "servicesToRequest": [], "bundleControlFilter": 2}, "trackingPoint": "BBV"}}}


def _bound(o: str, d: str, day: date, adults: int, cur: str) -> tuple[list[dict], str]:
    global _token
    key = f"vueling:{o}:{d}:{day}:{adults}:{cur}"
    if (hit := cache.get(key)) is None:
        with _lock:
            r = _s().post(f"{API}/avy/v1/graphql", json=_request(o, d, day, adults, cur),
                          headers={**_H, "Authorization": "Bearer " + _auth(), "Content-Type": "application/json"},
                          timeout=60)
            if r.status_code == 401:
                _token = None
                r = _s().post(f"{API}/avy/v1/graphql", json=_request(o, d, day, adults, cur),
                              headers={**_H, "Authorization": "Bearer " + _auth()}, timeout=60)
        r.raise_for_status()
        hit = r.json()
        if not (hit.get("data") or {}).get("amsAvy"):
            if hit.get("errors"):
                raise RuntimeError(f"vueling: {str(hit['errors'])[:150]}")
            hit = {"data": {"amsAvy": {"currencyCode": cur, "trips": [], "faresAvailable": []}}}
        cache.put(key, hit)
    return parse(hit, adults)


def search(q: SearchQuery) -> list[Itinerary]:
    if not relevant(q.origins, q.destinations):
        return []
    cur = "EUR"  # Vueling prices in EUR (GBP/CHF markets too, but EUR is always offered)
    out: list[Itinerary] = []
    for o in [c for c in q.origins if c in STATIONS][:2]:
        mk = markets(o)
        for d in [c for c in q.destinations if c in STATIONS][:2]:
            if o == d or (mk is not None and d not in mk):
                continue
            outs, c1 = _bound(o, d, q.departure, q.adults, cur)
            backs = None
            if q.return_date:
                if not outs:
                    continue
                backs, _ = _bound(d, o, q.return_date, q.adults, cur)
                if not backs:
                    continue
            out += combine(q, "vueling", "Vueling", outs, backs, c1,
                           deeplink(o, d, q.departure, q.return_date, q.adults, cur), NAMES,
                           note="Vueling Basic fare (small under seat bag only, cabin and checked bags extra).")
    return out
