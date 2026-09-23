"""Volotea (V7) direct from volotea.com's own backend (Navitaire dotREZ behind
api.volotea.com). Google Flights prices Volotea's regular fare correctly, but
Kiwi misses many Volotea nonstops, and Volotea is highly seasonal, so its own
schedule is the most reliable way to know whether a route flies at all.

No key: an anonymous session token comes from POST /account/login using the
public API key embedded in volotea.com's JS. Requests must look like Chrome at
the TLS level (curl_cffi impersonation), otherwise Akamai answers 403
(chrome_android impersonation and headless Playwright both get 403 on search).

Prices: we use the "Regular" fare (fareTypeCode R), which is what anyone can
book. Its fareAmount already includes taxes and the payment fee and matches the
price on the flight selection page. Cheaper "Mega" fares need a MegaVolotea
membership (free trial, then paid), so they are only mentioned in a warning.

dates() uses the static per route schedule JSON on json.volotea.com (rebuilt
every 30 minutes, about 13 months ahead, per flight prices by fare type). It
needs no session at all."""

from __future__ import annotations

import os

import threading
import time
from datetime import date, datetime

from curl_cffi import requests as cr

from .. import airports, cache, fx
from ..models import DatePrice, Itinerary, SearchQuery, Segment, Slice

API = "https://api.volotea.com/api/voe/v1"
STATIC = "https://json.volotea.com/dist"
# Public key from volotea.com's web app, kept out of this public repo. Set
# FLIGHTSCOUT_VOLOTEA_KEY to enable this source (browser dev tools, request
# header on api.volotea.com). The fare calendar (json.volotea.com) needs no key.
_API_KEY = os.environ.get("FLIGHTSCOUT_VOLOTEA_KEY", "")
_HEADERS = {
    "x-api-key": _API_KEY, "Content-Type": "application/json", "Accept": "application/json",
    "Origin": "https://book.volotea.com", "Referer": "https://book.volotea.com/",
}
_lock = threading.Lock()
_session: cr.Session | None = None
_token: tuple[str, float] | None = None
_last_call = 0.0
_MIN_GAP = 0.7  # seconds between live API calls, to stay polite

# Countries with Volotea airports (from stations.json, September 2026). Both
# ends must be in this set; stations.json markets then decide per route.
COUNTRIES = {"FR", "ES", "IT", "GR", "DE", "DZ", "HR", "PT", "DK", "MA", "BG", "BE", "CH", "AT",
             "NL", "LU", "MT", "CZ", "AL"}


def relevant(origins: list[str], destinations: list[str]) -> bool:
    def cc(codes):
        return {a.country for c in codes if (a := airports.get(c))}
    o, d = cc(origins), cc(destinations)
    return bool(o and d and (o | d) <= COUNTRIES)


def _sess() -> cr.Session:
    global _session
    if _session is None:
        _session = cr.Session(impersonate="chrome")
    return _session


def _stations() -> dict:
    data = cache.get("volotea:stations", ttl=24 * 3600)
    if data is None:
        with _lock:
            r = _sess().get(f"{STATIC}/stations/stations.json?v=1", timeout=30)
        r.raise_for_status()
        full = r.json()
        # keep only what we need: direct markets per station
        data = {code: sorted(dst for dst, m in (st.get("Markets") or {}).items()
                             if m.get("Enabled") and m.get("FlightType") in ("Direct", "Both"))
                for code, st in full.items() if st.get("Enabled")}
        cache.put("volotea:stations", data)
    return data


def has_route(origin: str, dest: str) -> bool:
    try:
        return dest in _stations().get(origin, [])
    except Exception:
        return True  # if the station list fails, let the live search decide


def _post(path: str, body: dict) -> dict:
    global _token, _last_call
    with _lock:
        s = _sess()
        if not _token or time.time() - _token[1] > 8 * 60:  # tokens idle out after 10 min
            r = s.post(f"{API}/account/login", json={}, headers=_HEADERS, timeout=20)
            r.raise_for_status()
            _token = (r.json()["data"]["token"], time.time())
        wait = _MIN_GAP - (time.time() - _last_call)
        if wait > 0:
            time.sleep(wait)
        r = s.post(f"{API}{path}", json=body, headers={**_HEADERS, "x-session-token": _token[0]}, timeout=30)
        _last_call = time.time()
        if r.status_code in (401, 440):
            _token = None
        r.raise_for_status()
        _token = (_token[0], time.time()) if _token else None
        return r.json()


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1) -> str:
    """Opens book.volotea.com's flight selection with the search prefilled
    (the booking app reads these query params into its search model)."""
    u = (f"https://book.volotea.com/booking/flights?from={origin}&to={dest}"
         f"&departuredate={dep.isoformat()}&adults={adults}&children=0&infants=0")
    if ret:
        u += f"&returndate={ret.isoformat()}"
    return u


def _is_mega(f: dict) -> bool:
    return "mega" in (f.get("fareType") or "").lower()


def _flights(origin: str, dest: str, day: date, adults: int) -> list[dict]:
    key = f"volotea:{origin}:{dest}:{day}:{adults}"
    if (hit := cache.get(key)) is not None:
        return hit
    body = {
        "criteria": [{"beginDate": day.isoformat(), "endDate": day.isoformat(), "selectedDate": day.isoformat(),
                      "origin": origin, "destination": dest}],
        "codes": {"currency": "EUR", "promotionCode": "", "bookingType": 2, "residentType": "NONE"},
        "passengers": [{"count": adults, "type": "ADT"}],
        "abTastyExperiments": [], "fareTypesToRequest": [],
    }
    d = _post("/flights/search", body)
    out = []
    for trip in (d.get("data") or {}).get("trips") or []:
        for j in trip.get("journeysAvailable") or []:
            if not j.get("hasFlights", True) or j["designator"]["departure"][:10] != day.isoformat():
                continue
            publics, megas = [], []
            for f in j.get("fares") or []:
                pf = next((p for p in f.get("passengerFares") or [] if p.get("passengerType") == "ADT"), None)
                if not pf or not f.get("availabilityCount"):
                    continue
                price = pf["fareAmount"]["amount"] * adults
                if _is_mega(f):
                    megas.append(price)
                else:  # prefer the Regular fare, else the cheapest other public fare
                    publics.append((f.get("fareTypeCode") != "R", price, f["availabilityCount"]))
            if not publics:
                continue
            _, p_price, p_seats = min(publics)
            public = (p_price, p_seats)
            mega = min(megas) if megas else None
            segs = [{
                "origin": s["designator"]["origin"], "destination": s["designator"]["destination"],
                "departure": s["designator"]["departure"], "arrival": s["designator"]["arrival"],
                "carrier": s["identifier"]["carrierCode"], "number": s["identifier"]["identifier"],
                "aircraft": ((s.get("legs") or [{}])[0].get("legInfo") or {}).get("equipmentType"),
            } for s in j["segments"]]
            dur = j.get("flightDuration") or ""
            try:
                h, m, _ = (int(x) for x in dur.split(":"))
                minutes = h * 60 + m
            except ValueError:
                minutes = None
            out.append({"segments": segs, "total": round(public[0], 2), "seats": public[1],
                        "mega": round(mega, 2) if mega is not None else None, "duration": minutes})
    cache.put(key, out)
    return out


def _slice(j: dict) -> Slice:
    segs = [Segment(origin=s["origin"], destination=s["destination"],
                    departure=datetime.fromisoformat(s["departure"]), arrival=datetime.fromisoformat(s["arrival"]),
                    carrier=s["carrier"], carrier_name="Volotea" if s["carrier"] == "V7" else None,
                    flight_number=s["number"], aircraft=s.get("aircraft")) for s in j["segments"]]
    dur = j.get("duration") or int((segs[-1].arrival - segs[0].departure).total_seconds() // 60)
    return Slice(segments=segs, duration_min=max(dur, 1))


def search(q: SearchQuery) -> list[Itinerary]:
    if not _API_KEY or not relevant(q.origins, q.destinations) or q.cabin != "economy":
        return []
    out: list[Itinerary] = []
    for o in q.origins[:3]:
        for d in q.destinations[:3]:
            if not has_route(o, d) or (q.return_date and not has_route(d, o)):
                continue
            outs = sorted(_flights(o, d, q.departure, q.adults), key=lambda x: x["total"])[:6]
            if not outs:
                continue
            backs = sorted(_flights(d, o, q.return_date, q.adults), key=lambda x: x["total"])[:6] \
                if q.return_date else [None]
            for a in outs:
                for b in backs:
                    slices = [_slice(a)] + ([_slice(b)] if b else [])
                    total = a["total"] + (b["total"] if b else 0)
                    warn = []
                    if a["seats"] <= 3 or (b and b["seats"] <= 3):
                        warn.append("Only a few seats left at this Volotea fare.")
                    mega = (a["mega"] or a["total"]) + ((b["mega"] or b["total"]) if b else 0)
                    if mega < total - 0.5:
                        warn.append(f"MegaVolotea members pay EUR {mega:.2f} (membership needed).")
                    out.append(Itinerary(
                        source="volotea", price=round(total, 2), currency="EUR", slices=slices,
                        booking_url=deeplink(o, d, q.departure, q.return_date, q.adults),
                        seller="Volotea", seller_kind="airline", warnings=warn,
                    ))
    return out


def dates(origin: str, dest: str, start: date, end: date, currency: str = "EUR") -> list[DatePrice]:
    """Cheapest public (Regular) fare per day from the static schedule file.
    One request covers the whole schedule (about 13 months) for the route."""
    pair = "-".join(sorted([origin, dest]))
    key = f"volotea-schedule:{pair}"
    data = cache.get(key, ttl=3 * 3600)
    if data is None:
        with _lock:
            r = _sess().get(f"{STATIC}/schedule/{pair}_schedule.json?v=1", timeout=30)
        if r.status_code == 404:
            return []
        r.raise_for_status()
        data = r.json()
        cache.put(key, data)
    best: dict[date, float] = {}
    for f in data.get(f"{origin}-{dest}") or []:
        if not f.get("Prices") or f.get("ConnectionInformation") or not f.get("AvailableSeats"):
            continue
        day = datetime.strptime(f["Departure"][:8], "%Y%m%d").date()
        if not (start <= day <= end):
            continue
        reg = [p["PriceWithFee"] for p in f["Prices"] if p.get("FareType") == "R"]
        if not reg:
            continue
        if day not in best or reg[0] < best[day]:
            best[day] = reg[0]
    out = []
    for day, price in sorted(best.items()):
        if currency.upper() != "EUR":
            price = fx.convert(price, "EUR", currency)
        out.append(DatePrice(origin=origin, destination=dest, departure=day, price=round(price, 2),
                             currency=currency.upper(), source="volotea",
                             booking_url=deeplink(origin, dest, day)))
    return out
