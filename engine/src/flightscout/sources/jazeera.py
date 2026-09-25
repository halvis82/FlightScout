"""Jazeera Airways (J9) direct from jazeeraairways.com. Kuwait based low cost
carrier (Gulf, Levant, Egypt, Turkey, Central and South Asia, a few European
summer routes) that Kiwi covers only partly.

Plain HTTP, no browser: the website's Next.js backend proxies Navitaire for
the browser. We do what the results page does:

1. ``POST /api/auth`` returns an anonymous access token (the literal
   ``client_id: WEB_CLIENT_ID`` headers are what the site's own JS sends; the
   server swaps in the real credentials).
2. ``POST /api/flights`` with that token returns every flight with its fare
   SKUs. ``totalFare`` of the base SKU (bundleId null, "Light" / ``EL``) is
   the price for all passengers incl. taxes, which is the "Lowest fare" the
   results page shows. The other SKUs (Comfort, Flex, ...) are bundle add on
   amounts on top of it, so they are ignored.

Route list: the search panel GraphQL (``/api/search`` GetSearchPanelData)
lists every airport with its bookable destinations (direct and via Kuwait).
Round trips are one call; Jazeera prices each direction on its own, in the
origin's currency (KWD from Kuwait, AED from the UAE, ...)."""

from __future__ import annotations

import base64
import re
import threading
import time
from datetime import date

from curl_cffi import requests as cr

from .. import cache
from ..models import Itinerary, SearchQuery
from ._airline import combine

SITE = "https://www.jazeeraairways.com"
NAMES = {"J9": "Jazeera Airways"}
_H = {"Origin": SITE, "Referer": f"{SITE}/en-kw/flights", "Accept": "application/json"}
_lock = threading.Lock()
_session: cr.Session | None = None
_token: tuple[str, float] | None = None


def _s() -> cr.Session:
    global _session
    if _session is None:
        _session = cr.Session(impersonate="chrome")
    return _session


def _auth() -> str:
    global _token
    with _lock:
        if _token and time.time() - _token[1] < 10 * 60:  # the site refreshes every 13 min
            return _token[0]
        r = _s().post(f"{SITE}/api/auth", data="", timeout=30, headers={
            **_H, "Content-Type": "application/json", "client_id": "WEB_CLIENT_ID",
            "client_secret": "WEB_SECRET", "scope": "WEB_SCOPE"})
        r.raise_for_status()
        j = r.json()
        tok = j.get("accessToken") or j.get("token") or j.get("access_token")
        if not tok:
            raise RuntimeError("jazeera: no anonymous token from /api/auth")
        _token = (tok, time.time())
        return tok


def network() -> dict[str, list[str]]:
    """Jazeera airport -> bookable destinations, from the search panel."""
    key = "jazeera:network"
    if (hit := cache.get(key, ttl=3 * 86400)) is not None:
        return hit
    q = '{"operationName":"GetSearchPanelData","variables":{},"query":"query GetSearchPanelData { getSearchPanelData { cities { airports { code destination { code } } } } }"}'
    r = _s().post(f"{SITE}/api/search", data=q, timeout=30, headers={
        **_H, "Content-Type": "application/json", "channel_id": "WEB", "authorization": f"Bearer {_auth()}"})
    r.raise_for_status()
    net = {a["code"]: sorted({x["code"] for x in a.get("destination") or []})
           for c in r.json()["data"]["getSearchPanelData"]["cities"] for a in c.get("airports") or []}
    if net:
        cache.put(key, net)
    return net


def relevant(origins: list[str], destinations: list[str]) -> bool:
    try:
        net = network()
    except Exception:
        return False
    return any(d in net.get(o, ()) for o in origins for d in destinations)


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1) -> str:
    u = (f"{SITE}/en-kw/flights?tripType={'roundtrip' if ret else 'oneway'}&origin={origin}"
         f"&destination={dest}&departureDate={dep.isoformat()}")
    if ret:
        u += f"&returnDate={ret.isoformat()}"
    return u + f"&adults={adults}&children=0&infants=0"


def _minutes(s: str | None) -> int | None:
    m = re.fullmatch(r"\s*(?:(\d+)h)?\s*(?:(\d+)m)?\s*", s or "")
    if not m or not any(m.groups()):
        return None
    return int(m.group(1) or 0) * 60 + int(m.group(2) or 0)


def _flight_from_id(fid: str) -> dict | None:
    """Fallback when a flight is missing from the ``flights`` list: the id is
    base64 of "J9\x7f 121~ ~~KWI\x7f11/10/2026 06:55~DXB\x7f11/10/2026 10:10~"."""
    try:
        raw = base64.b64decode(fid.replace("_", "/").replace("-", "=") + "==").decode("latin-1")
        p = re.split(r"[~\x7f]", raw)
        carrier, number = p[0].strip(), p[1].strip()
        o, dep, d, arr = [x for x in p[2:] if x.strip()][:4]
        iso = lambda t: f"{t[6:10]}-{t[0:2]}-{t[3:5]}T{t[11:16]}:00"  # noqa: E731
        return {"origin": o, "destination": d, "departure": iso(dep), "arrival": iso(arr),
                "carrier": carrier, "number": number}
    except Exception:
        return None


def parse(data: dict) -> list[tuple[str, str, str, list[dict]]]:
    """/api/flights JSON -> [(origin, destination, currency, journeys)] per
    direction. Each journey keeps the base (lowest) fare for all passengers."""
    res = data.get("FlightOffersResultV2") or {}
    out = []
    for c in res.get("connections") or []:
        fl = {f["flightId"]: f for f in c.get("flights") or []}
        js = []
        for fp in c.get("flightProducts") or []:
            base = [k for k in fp.get("flightSKUs") or [] if not (k.get("fareDetails") or {}).get("bundleId")]
            prices = [(float(k["fareDetails"]["totalFare"]), k) for k in base if k["fareDetails"].get("totalFare")]
            if not prices:
                continue
            total, sku = min(prices, key=lambda x: x[0])
            segs = []
            for s in fp.get("segments") or []:
                f = fl.get(s["flightId"])
                if f:
                    segs.append({"origin": f["departureAirportCode"], "destination": f["arrivalAirportCode"],
                                 "departure": f["departureTime"], "arrival": f["arrivalTime"],
                                 "carrier": f["carrierCode"], "number": f["flightNumber"].strip(),
                                 "duration": _minutes(f.get("duration")), "aircraft": f.get("equipmentCode")})
                elif g := _flight_from_id(s["flightId"]):
                    segs.append(g)
                else:
                    break
            else:
                if segs:
                    js.append({"segments": segs, "total": total, "seats": sku.get("seatCount"),
                               "fare": sku.get("SKUCode"), "duration": _minutes(fp.get("duration"))})
        out.append((c.get("origin"), c.get("destination"), c.get("currencyCode"), js))
    return out


def _fetch(o: str, d: str, dep: date, ret: date | None, adults: int) -> dict:
    key = f"jazeera:{o}:{d}:{dep}:{ret}:{adults}"
    if (hit := cache.get(key)) is not None:
        return hit
    body = {"tripType": "roundtrip" if ret else "oneway", "origin": o, "destination": d,
            "departureDate": f"{dep:%d-%m-%Y}", "currencyCode": "",
            "passengerDetails": {"adult": str(adults), "child": "0", "infant": "0", "duoSeat": "0",
                                 "unAccompaniedMinor": "0"},
            "token": _auth(), "promoCode": "", "searchEngineType": "", "multiCityData": []}
    if ret:
        body["returnDate"] = f"{ret:%d-%m-%Y}"
    r = _s().post(f"{SITE}/api/flights", json=body, headers=_H, timeout=45)
    if r.status_code in (401, 403):
        global _token
        _token = None
        body["token"] = _auth()
        r = _s().post(f"{SITE}/api/flights", json=body, headers=_H, timeout=45)
    r.raise_for_status()
    data = r.json()
    if "FlightOffersResultV2" not in data:
        raise RuntimeError(f"jazeera: unexpected response {r.text[:150]!r}")
    cache.put(key, data)
    return data


def search(q: SearchQuery) -> list[Itinerary]:
    if q.cabin != "economy" or not relevant(q.origins, q.destinations):
        return []
    net = network()
    out: list[Itinerary] = []
    for o in q.origins[:3]:
        for d in q.destinations[:3]:
            if d not in net.get(o, ()):
                continue
            bounds = parse(_fetch(o, d, q.departure, q.return_date, q.adults))
            outs = next((b for b in bounds if b[0] == o), None)
            backs = next((b for b in bounds if b[0] == d), None) if q.return_date else None
            if not outs or not outs[3] or (q.return_date and not (backs and backs[3])):
                continue
            out += combine(q, "jazeera", "Jazeera Airways", outs[3], backs[3] if backs else None, outs[2],
                           deeplink(o, d, q.departure, q.return_date, q.adults), NAMES,
                           note="Jazeera Light fare (lowest; checked bags extra).")
    return out
