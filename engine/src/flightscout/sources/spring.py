"""Spring Airlines (9C, China) direct from en.ch.com. Shanghai based low cost
carrier that sells mostly on its own site (thin on Google and Kiwi): Chinese
domestic plus Japan, Korea and Southeast Asia from Shanghai and other Chinese
cities.

Plain HTTP, no browser, no key: the flight selection page loads its results
with ``POST /Flights/SearchByTime`` (form encoded, one direction per call,
city codes like SHA, OSA, TYO), which answers plain Chrome TLS clients after a
first GET of the home page for cookies. One call per direction, about a second
each.

Prices: ``MinCabinPrice`` per adult already includes the airport construction
fee and fuel surcharge (``RouteTotalTax``). The flight selection page shows
the same number and its (i) breakdown adds up to it. Verified September 2026
(headless render): PVG-KIX 22 Oct 2026 9C6575 CNY 1,002 here and on the page
("Adult CNY 600 + Airport Construction Fee / Fuel Surcharge CNY 402");
SHA-SZX 9C8881 CNY 600 both ("Total CNY 600"). Round trips are two one ways,
which is how the site prices them (it selects each direction on its own).
Only nonstop flights are kept (connections are rare on 9C)."""

from __future__ import annotations

import re
import threading
from datetime import date

from curl_cffi import requests as cr

from .. import cache
from ..models import Itinerary, SearchQuery
from ._airline import combine, countries

SITE = "https://en.ch.com"
NAMES = {"9C": "Spring Airlines"}
CURRENCY = "CNY"
_H = {"X-Requested-With": "XMLHttpRequest", "Referer": f"{SITE}/flights", "Origin": SITE,
      "Accept": "application/json, text/javascript, */*; q=0.01"}
# Spring searches by city: airport -> the city code its search takes.
CITY = {"PVG": "SHA", "NRT": "TYO", "HND": "TYO", "KIX": "OSA", "ITM": "OSA", "PEK": "BJS", "PKX": "BJS",
        "ICN": "SEL", "GMP": "SEL", "DMK": "BKK", "TFU": "CTU", "CTS": "SPK"}
# Every Spring route touches mainland China; the other end is in East,
# Southeast or Central Asia.
AREA = {"CN", "JP", "KR", "TH", "SG", "MY", "KH", "VN", "HK", "MO", "TW", "ID", "PH", "BD", "LK", "KZ", "UZ",
        "KG", "LA", "MM", "NP"}
_lock = threading.Lock()
_session: cr.Session | None = None


def _s() -> cr.Session:
    global _session
    with _lock:
        if _session is None:
            _session = cr.Session(impersonate="chrome")
            _session.get(SITE + "/", timeout=30)
        return _session


def relevant(origins: list[str], destinations: list[str]) -> bool:
    oc, dc = countries(origins), countries(destinations)
    return bool(("CN" in oc and dc & AREA) or ("CN" in dc and oc & AREA))


def city(code: str) -> str:
    return CITY.get(code, code)


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1) -> str:
    return (f"{SITE}/flights/{city(origin)}-{city(dest)}.html?FDate={dep.isoformat()}"
            f"&RetDate={ret.isoformat() if ret else ''}&ANum={adults}&CNum=0&INum=0"
            f"&IfRet={'true' if ret else 'false'}&MType=0")


def _minutes(s: str | None) -> int | None:
    m = re.fullmatch(r"\s*(\d+)\s*H\s*(\d+)\s*M\s*", s or "", re.IGNORECASE)
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def parse(data: dict, adults: int = 1, day: date | None = None) -> list[dict]:
    """SearchByTime JSON -> nonstop journeys at the cheapest fare incl. taxes
    for ``adults`` adults."""
    out = []
    for route in data.get("Route") or []:
        if not isinstance(route, list) or len(route) != 1:
            continue
        f = route[0]
        price = f.get("MinCabinPrice")
        if not price or f.get("Stopovers") or f.get("Bus"):
            continue
        if day and not str(f.get("DepartureTime", "")).startswith(day.isoformat()):
            continue
        no = str(f.get("No") or "")
        carrier, number = (no[:2], no[2:]) if len(no) > 2 else ("9C", no)
        dur = _minutes(f.get("FlightTime"))
        out.append({
            "segments": [{"origin": f["DepartureAirportCode"], "destination": f["ArrivalAirportCode"],
                          "departure": f["DepartureTime"].replace(" ", "T"),
                          "arrival": f["ArrivalTime"].replace(" ", "T"),
                          "carrier": carrier, "number": number, "duration": dur, "aircraft": f.get("Type")}],
            "total": round(float(price) * adults, 2), "duration": dur, "seats": None,
        })
    return out


def _fetch(o: str, d: str, day: date, adults: int) -> dict:
    key = f"spring:{o}:{d}:{day}:{adults}"
    if (hit := cache.get(key)) is not None:
        return hit
    form = {"Departure": o, "Arrival": d, "DepartureDate": day.isoformat(), "ReturnDate": "",
            "IsIJFlight": "false", "SType": "0", "Currency": CURRENCY, "AdtNum": str(adults),
            "ChdNum": "0", "InfNum": "0"}
    r = _s().post(f"{SITE}/Flights/SearchByTime", data=form, headers=_H, timeout=30)
    r.raise_for_status()
    data = r.json()
    if data.get("Code") != "0":
        raise RuntimeError(f"spring: {data.get('Code')} {str(data.get('ErrorMessage'))[:100]}")
    cache.put(key, data)
    return data


def _bound(o_codes: list[str], d_codes: list[str], day: date, adults: int) -> list[dict]:
    out: list[dict] = []
    for o in dict.fromkeys(city(c) for c in o_codes):
        for d in dict.fromkeys(city(c) for c in d_codes):
            if o != d:
                out += parse(_fetch(o, d, day, adults), adults, day)
    # the city search can include the metro's other airport: keep the asked ones
    return [j for j in out if j["segments"][0]["origin"] in o_codes and j["segments"][-1]["destination"] in d_codes]


def search(q: SearchQuery) -> list[Itinerary]:
    if q.cabin != "economy" or not relevant(q.origins, q.destinations):
        return []
    os_ = [c for c in q.origins if "CN" in countries([c]) or countries([c]) & AREA][:3]
    ds = [c for c in q.destinations if "CN" in countries([c]) or countries([c]) & AREA][:3]
    outs = _bound(os_, ds, q.departure, q.adults)
    if not outs:
        return []
    backs = _bound(ds, os_, q.return_date, q.adults) if q.return_date else None
    if q.return_date and not backs:
        return []
    o, d = outs[0]["segments"][0]["origin"], outs[0]["segments"][-1]["destination"]
    return combine(q, "spring", "Spring Airlines", outs, backs, CURRENCY,
                   deeplink(o, d, q.departure, q.return_date, q.adults), NAMES,
                   note="Spring Airlines SpringSaver fare incl. taxes (7 kg carry on, no checked bag).")
