"""SpiceJet (SG) direct from spicejet.com through the shared real Chrome (see
_browser.py). Akamai answers 403 to plain HTTP clients on the search API (the
home page and the anonymous token work, the availability call does not), so
we open the site's own search deeplink (/search?from=..&to=..) headless and
capture the availability JSON its app fetches (/api/v3/search/availability,
a thin wrapper over Navitaire dotREZ).

``fareAmount`` per passenger already includes taxes and fees (the page says
"All the fare include taxes and fee" and shows exactly these numbers). A round
trip deeplink returns both directions in one response and the site totals it
as outbound fare + return fare, which is what we do too. About 10 to 15
seconds per search, headless."""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta, timezone

from .. import cache
from ..models import Itinerary, SearchQuery
from . import _browser
from ._airline import combine

log = logging.getLogger(__name__)
SITE = "https://www.spicejet.com"
NAMES = {"SG": "SpiceJet"}
# Active SpiceJet stations (the site's getStationDetails list, September 2026;
# that endpoint is behind Akamai too, so it is kept here). A SpiceJet ticket
# always touches India.
STATIONS = {
    "AGR", "AIP", "AMD", "ATQ", "AUH", "AYJ", "BBI", "BDQ", "BGW", "BHU", "BKB", "BKK", "BLR", "BOM", "CCJ",
    "CCU", "CMB", "COK", "DBR", "DED", "DEL", "DHM", "DOH", "DWC", "DXB", "FJR", "GAU", "GOI", "GOP", "GOX",
    "HJR", "HKT", "HSR", "HWR", "HYD", "IDR", "IMF", "IXB", "IXC", "IXD", "IXJ", "IXL", "IXM", "IXR", "IXU",
    "IXY", "IXZ", "JAI", "JDH", "JED", "JGA", "JSA", "KNU", "KTM", "LKO", "MAA", "MCT", "MED", "MFM", "MLE",
    "NAG", "NJF", "PAT", "PBD", "PNQ", "RKT", "RPR", "RQY", "RUH", "SHJ", "SHL", "STV", "SXR", "TCR", "TIR",
    "TRV", "UDR", "VNS", "VTZ",
}
ABROAD = {"AUH", "BGW", "BKK", "CMB", "DOH", "DWC", "DXB", "HKT", "JED", "KTM", "MCT", "MED", "MFM", "MLE",
          "NJF", "RKT", "RUH", "SHJ"}


def available() -> bool:
    return _browser.available()


def relevant(origins: list[str], destinations: list[str]) -> bool:
    if not available():
        return False
    o = [c for c in origins if c in STATIONS]
    d = [c for c in destinations if c in STATIONS]
    return bool(o and d) and any(c not in ABROAD for c in o + d)


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1,
             currency: str = "INR") -> str:
    u = (f"{SITE}/search?from={origin}&to={dest}&tripType={2 if ret else 1}&departure={dep.isoformat()}"
         f"&adult={adults}&child=0&infant=0&currency={currency}&redirectTo=/")
    if ret:
        u = u.replace("&adult=", f"&return={ret.isoformat()}&adult=")
    return u


_DUR = re.compile(r"(?:(\d+)h)?\s*(?:(\d+)m)?")


def _iso(local: str, offset_min: int | None) -> str:
    dt = datetime.fromisoformat(local)
    if offset_min is not None:
        dt = dt.replace(tzinfo=timezone(timedelta(minutes=offset_min)))
    return dt.isoformat()


def parse(data: dict, adults: int = 1) -> tuple[list[list[dict]], str | None]:
    """availability JSON -> ([outbound journeys, return journeys], currency).
    Each journey keeps its cheapest fare; totals are for ``adults`` adults."""
    d = data.get("data") or {}
    fares = d.get("faresAvailable") or {}
    tz = d.get("stationCodeTimeZoneOffsets") or {}
    out: list[list[dict]] = []
    for trip in d.get("trips") or []:
        js = []
        for j in trip.get("journeysAvailable") or []:
            if j.get("notForGeneralUser"):
                continue
            best = None
            for key, info in (j.get("fares") or {}).items():
                f = fares.get(key)
                if not f:
                    continue
                pf = next((p for p in f.get("passengerFares") or [] if p.get("passengerType") == "ADT"), None)
                if pf is None or pf.get("fareAmount") is None:
                    continue
                seats = info.get("availableCount") if isinstance(info, dict) else None
                if best is None or pf["fareAmount"] < best[0]:
                    best = (pf["fareAmount"], f.get("productClass"), seats)
            if not best:
                continue
            segs = []
            for s in j.get("segments") or []:
                des, ident = s["designator"], s["identifier"]
                segs.append({"origin": des["origin"], "destination": des["destination"],
                             "departure": _iso(des["departure"], tz.get(des["origin"])),
                             "arrival": _iso(des["arrival"], tz.get(des["destination"])),
                             "carrier": ident["carrierCode"], "number": ident["identifier"]})
            if not segs:
                continue
            js.append({"segments": segs, "total": round(best[0] * adults, 2), "fare": best[1],
                       "seats": best[2]})
        out.append(js)
    return out, d.get("currencyCode")


def _fetch(url: str) -> dict:
    def job(page) -> str:
        got = _browser.capture(page, lambda: page.goto(url, wait_until="commit", timeout=45000),
                               lambda u: "/api/v3/search/availability" in u, timeout=40)
        return got[-1][1] if got else ""

    txt = _browser.run(job, "spicejet", timeout=120)
    if not txt:
        raise RuntimeError("spicejet: no availability response")
    d = json.loads(txt)
    if "data" not in d:
        raise RuntimeError(f"spicejet: error response {txt[:150]!r}")
    return d


def search(q: SearchQuery) -> list[Itinerary]:
    if not relevant(q.origins, q.destinations):
        return []
    out: list[Itinerary] = []
    for o in [c for c in q.origins if c in STATIONS][:2]:
        for d in [c for c in q.destinations if c in STATIONS][:2]:
            if o == d or (o in ABROAD and d in ABROAD):
                continue
            url = deeplink(o, d, q.departure, q.return_date, q.adults)
            key = f"spicejet:{o}:{d}:{q.departure}:{q.return_date}:{q.adults}"
            if (raw := cache.get(key)) is None:
                raw = _fetch(url)
                cache.put(key, raw)
            trips, cur = parse(raw, q.adults)
            outs = trips[0] if trips else []
            backs = (trips[1] if len(trips) > 1 else []) if q.return_date else None
            if not outs or (q.return_date and not backs):
                continue
            out += combine(q, "spicejet", "SpiceJet", outs, backs, cur or "INR", url, NAMES,
                           note="SpiceJet cheapest fare (usually SpiceSaver).")
    return out
