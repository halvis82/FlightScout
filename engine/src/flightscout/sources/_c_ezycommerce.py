"""Shared client for airlines on Sabre EzyCommerce (formerly Radixx, the
"booksecure" booking app): SKY express uses it, and so do Arajet, Nok Air,
Air Japan, Evelop and others, each on its own booking host.

Everything is plain HTTP JSON (no bot manager in front of the API). The only
credential is the tenant key the booking app ships to every visitor in its
page HTML (``window.runtimeConfig = {"apiHost": ..., "apiKey": ...}``); we
read it from the airline's booking host at runtime (cached a day) and send it
as the ``Tenant-Identifier`` header, like the app does.

- ``/Airport/OriginsWithConnections/en-us``: every origin with the airports
  sellable from it (direct or connecting), the network gate.
- ``/Availability/SearchShop``: flights with every fare family for one or more
  routes (a round trip is one request with two routes, which is how the site
  prices it: some families are cheaper on a round trip). Fare ``price`` is the
  total for all passengers incl. taxes, exactly what the flight selection page
  shows."""

from __future__ import annotations

import json
import threading
from datetime import date, datetime

from curl_cffi import requests as cr

from .. import cache

_lock = threading.Lock()
_session: cr.Session | None = None
_CABIN = {"economy": "ECONOMY", "business": "BUSINESS", "first": "BUSINESS"}


def _s() -> cr.Session:
    global _session
    with _lock:
        if _session is None:
            _session = cr.Session(impersonate="chrome")
        return _session


class Ezy:
    def __init__(self, key: str, host: str):
        self.key = key  # cache namespace, e.g. "skyexpress"
        self.host = host  # the airline's booking app, e.g. "https://flights.skyexpress.gr"

    def config(self) -> tuple[str, str]:
        """(apiHost, tenant key) from the booking app's runtimeConfig."""
        ck = f"ezy:{self.key}:config"
        if (hit := cache.get(ck, ttl=86400)) and hit[0] and hit[1]:
            return hit[0], hit[1]
        html = _s().get(self.host + "/", timeout=30).text
        i = html.find("runtimeConfig = ")
        if i < 0:
            raise RuntimeError(f"{self.key}: no runtimeConfig on {self.host}")
        cfg, _ = json.JSONDecoder().raw_decode(html, i + len("runtimeConfig = "))
        out = [cfg["apiHost"].rstrip("/"), cfg["apiKey"]]
        cache.put(ck, out)
        return out[0], out[1]

    def _headers(self, key: str) -> dict:
        return {"Tenant-Identifier": key, "Accept": "text/plain", "Content-Type": "application/json",
                "languagecode": "en-us", "appcontext": "ibe", "Origin": self.host, "Referer": self.host + "/"}

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        api, key = self.config()
        r = _s().request(method, f"{api}/api/v1{path}", json=body, headers=self._headers(key), timeout=60)
        if r.status_code in (401, 403):  # rotated tenant key: read the page again once
            cache.put(f"ezy:{self.key}:config", None)
            api, key = self.config()
            r = _s().request(method, f"{api}/api/v1{path}", json=body, headers=self._headers(key), timeout=60)
        r.raise_for_status()
        return r.json()

    def network(self) -> dict[str, list[str]] | None:
        """origin -> sellable destinations, or None if the list is unavailable."""
        ck = f"ezy:{self.key}:network"
        if (hit := cache.get(ck, ttl=7 * 86400)) is not None:
            return hit
        try:
            data = self._call("GET", "/Airport/OriginsWithConnections/en-us")
            net = {a["code"]: sorted(c["code"] for c in a.get("connections") or [])
                   for a in data.get("airports") or []}
        except Exception:
            return None
        if net:
            cache.put(ck, net)
        return net or None

    def has_route(self, o: str, d: str) -> bool | None:
        net = self.network()
        if net is None:
            return None
        return d in net.get(o, [])

    def shop(self, legs: list[tuple[str, str, date]], adults: int, currency: str) -> dict:
        ck = f"ezy:{self.key}:shop:{legs}:{adults}:{currency}"
        if (hit := cache.get(ck)) is not None:
            return hit
        body = {
            "passengers": [{"code": "ADT", "count": adults}, {"code": "CHD", "count": 0},
                           {"code": "INF", "count": 0}],
            "routes": [{"fromAirport": o, "toAirport": d, "departureDate": day.isoformat(),
                        "startDate": day.isoformat(), "endDate": day.isoformat()} for o, d, day in legs],
            "currency": currency, "fareTypeCategories": None, "isManageBooking": False, "languageCode": "en-us",
        }
        data = self._call("POST", "/Availability/SearchShop", body)
        cache.put(ck, data)
        return data

    def deeplink(self, legs: list[tuple[str, str, date]], adults: int, currency: str) -> str:
        q = "&".join(f"routes[{i}][from]={o}&routes[{i}][to]={d}&routes[{i}][date]={day.isoformat()}"
                     for i, (o, d, day) in enumerate(legs))
        return f"{self.host}/?{q}&passengers[0][code]=ADT&passengers[0][count]={adults}&currency={currency}&execute=true"


def parse(data: dict, route: int = 0, cabin: str = "economy", day: date | None = None) -> list[dict]:
    """SearchShop response -> journey dicts for ``routes[route]``, cheapest
    fare family of the cabin per flight (total for all passengers)."""
    want = _CABIN.get(cabin)
    routes = data.get("routes") or []
    if want is None or route >= len(routes):
        return []
    out = []
    for f in routes[route].get("flights") or []:
        if f.get("soldOut") or f.get("isPlaceHolder"):
            continue
        if day and not str(f.get("departureDate", "")).startswith(day.isoformat()):
            continue
        fares = [x for x in f.get("fares") or [] if x.get("cabin", f.get("cabin")) == want and x.get("price")]
        if not fares:
            continue
        best = min(fares, key=lambda x: x["price"])
        segs = [{
            "origin": lg["from"]["code"], "destination": lg["to"]["code"],
            "departure": lg["departureDate"], "arrival": lg["arrivalDate"],
            "carrier": lg.get("operatingCarrierCode") or lg["carrierCode"], "number": str(lg["flightNumber"]),
            "duration": lg.get("flightTime"), "aircraft": lg.get("equipmentType"),
        } for lg in f.get("legs") or []]
        if not segs:
            continue
        dur = f.get("flightTime")
        if f.get("departureDateTimeOffset") and f.get("arrivalDateTimeOffset"):
            dur = int((datetime.fromisoformat(f["arrivalDateTimeOffset"])
                       - datetime.fromisoformat(f["departureDateTimeOffset"])).total_seconds() // 60)
        out.append({"segments": segs, "total": round(best["price"], 2), "fare": best.get("name"),
                    "seats": (best.get("adult") or {}).get("seatCount") or best.get("seatCount"), "duration": dur})
    return out
