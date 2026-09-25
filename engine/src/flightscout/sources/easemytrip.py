"""EaseMyTrip (easemytrip.com, India) through the JSON endpoint its own
results page posts to: flightservice-node.easemytrip.com/AirAvail_Lights/
AirBus_New (keyless, Chrome TLS impersonation, plain HTTP).

One POST per direction returns every one way offer (1 to 4 MB, 1 to 4
seconds) with its fare families; ``TF`` of the cheapest family is the total
for all passengers incl. taxes, exactly the "₹6,832" on the listing page
(before optional coupon codes, which we ignore). Segments come in
``dctFltDtl`` with local dates and times.

Round trips: EaseMyTrip sells Indian domestic round trips as two one way
fares side by side, and its international round trip answer is huge (40+ MB),
so we price both directions as one way searches and combine them as two
separate tickets (said so in the warnings). Prices are in INR.

Unofficial: fails soft."""

from __future__ import annotations

import hashlib
import re
import threading
import time
from datetime import date, datetime
from urllib.parse import quote

from curl_cffi import requests as cr

from .. import airports, cache
from ..models import Itinerary, SearchQuery, Segment, Slice

SITE = "https://www.easemytrip.com"
API = "https://flightservice-node.easemytrip.com/AirAvail_Lights/AirBus_New"
_CABIN = {"economy": 0, "first": 1, "business": 2, "premium": 4}
NOTE = "Sold by EaseMyTrip (Indian travel agency), not the airline."
TWO_OW = ("Two separate one way tickets on EaseMyTrip (outbound and return priced alone): a delay or "
          "cancellation on one does not protect the other.")
_local = threading.local()


def relevant(origins: list[str], destinations: list[str]) -> bool:
    return True  # sells worldwide, strongest in and out of India


def _session() -> cr.Session:
    if not hasattr(_local, "s"):
        _local.s = cr.Session(impersonate="chrome")
    return _local.s


def _india(*codes: str) -> bool:
    return all((a := airports.get(c)) is not None and a.country == "IN" for c in codes)


def search_url(o: str, d: str, dep: date, ret: date | None = None, adults: int = 1, cabin: str = "economy") -> str:
    srch = f"{o}-{o}|{d}-{d}|{dep:%d/%m/%Y}" + (f"-{ret:%d/%m/%Y}" if ret else "")
    return (f"{SITE}/flight-search/listing?srch={quote(srch, safe='|-')}&px={adults}-0-0&cbn={_CABIN.get(cabin, 0)}"
            f"&ar=undefined&isow={'false' if ret else 'true'}&isdm={'true' if _india(o, d) else 'false'}"
            f"&lang=en-us&CCODE=IN&curr=INR&apptype=B2C")


def _body(o: str, d: str, day: date, adults: int, cabin: str) -> dict:
    trace = hashlib.md5(f"{o}{d}{day}{time.time()}".encode()).hexdigest()
    return {"org": o, "dept": d, "adt": adults, "chd": 0, "inf": 0, "deptDT": day.isoformat(), "arrDT": "",
            "userid": "", "IsDoubelSeat": False, "isDomestic": _india(o, d), "isOneway": True, "airline": "undefined",
            "Cabin": _CABIN.get(cabin, 0), "currCode": "INR", "appType": 1, "isSingleView": False, "ResType": 2,
            "IsNBA": False, "CouponCode": "", "IsArmedForce": False, "AgentCode": "", "IsWLAPP": False,
            "IsFareFamily": False, "serviceid": "EMTSERVICE", "serviceDepatment": "", "IpAddress": "", "LoginKey": "",
            "UUID": "", "TKN": "", "TraceId": trace, "queryname": trace, "FareTypeUI": 0}


def _dt(day: str, hhmm: str) -> datetime:
    """'Thu-12Nov2026' + '21:50'."""
    return datetime.strptime(f"{day.split('-', 1)[-1]} {hhmm}", "%d%b%Y %H:%M")


def _mins(s: str | None) -> int | None:
    m = re.fullmatch(r"\s*(\d+)h\s*:?\s*(\d+)m\s*", s or "")
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def parse(data: dict, o: str, d: str, max_stops: int | None = None) -> list[tuple[float, Slice, dict]]:
    """AirBus_New JSON -> (total price, slice, raw offer) between exactly o and d,
    cheapest per flight combination."""
    det = data.get("dctFltDtl") or {}
    names = data.get("C") or {}
    best: dict[str, tuple[float, Slice, dict]] = {}
    for j in data.get("j") or []:
        for s in j.get("s") or []:
            price = s.get("TF")
            bounds = s.get("b") or []
            if price is None or not bounds:
                continue
            try:
                segs = []
                for fid in bounds[0].get("FL") or []:
                    f = det[str(fid)]
                    dep, arr = _dt(f["DDT"], f["DTM"]), _dt(f.get("ADT") or f["DDT"], f["ATM"])
                    segs.append(Segment(
                        origin=f["OG"], destination=f["DT"], departure=dep, arrival=arr, carrier=f["AC"].strip(),
                        carrier_name=f.get("FlightName") or names.get(f["AC"].strip()),
                        flight_number=str(f["FN"]).strip(), duration_min=_mins(f.get("DUR")),
                        aircraft=f.get("ET") or None))
            except (KeyError, ValueError):
                continue
            if not segs or segs[0].origin != o or segs[-1].destination != d:
                continue  # EaseMyTrip mixes in nearby airports (NMI for BOM)
            if max_stops is not None and len(segs) - 1 > max_stops:
                continue
            total = _mins(bounds[0].get("JyTm")) or int((segs[-1].arrival - segs[0].departure).total_seconds() // 60)
            sl = Slice(segments=segs, duration_min=max(1, total))
            key = "|".join(f"{x.carrier}{x.flight_number}{x.departure:%m%d%H%M}" for x in segs)
            if key not in best or float(price) < best[key][0]:
                best[key] = (float(price), sl, s)
    return sorted(best.values(), key=lambda x: x[0])


def _fetch(o: str, d: str, day: date, adults: int, cabin: str) -> dict:
    key = f"easemytrip:{o}:{d}:{day}:{adults}:{cabin}"
    if (hit := cache.get(key, ttl=20 * 60)) is not None:
        return hit
    r = _session().post(f"{API}?_={int(time.time() * 1000)}", json=_body(o, d, day, adults, cabin), timeout=60,
                        headers={"Origin": SITE, "Referer": SITE + "/flight-search/listing",
                                 "Accept": "application/json, text/plain, */*"})
    if r.status_code != 200 or "json" not in r.headers.get("content-type", ""):
        raise RuntimeError(f"easemytrip: HTTP {r.status_code} {r.text[:120]!r}")
    data = r.json()
    if not isinstance(data, dict):
        raise RuntimeError(f"easemytrip: {str(data)[:150]}")
    # keep only what parse() reads (the raw answer is megabytes)
    slim = {"C": data.get("C"), "dctFltDtl": data.get("dctFltDtl") or {}, "j": [
        {"s": [{"TF": s.get("TF"), "b": [{"FL": b.get("FL"), "JyTm": b.get("JyTm")} for b in s.get("b") or []]}
               for s in j.get("s") or []]} for j in data.get("j") or []]}
    cache.put(key, slim)
    return slim


def search(q: SearchQuery) -> list[Itinerary]:
    out: list[Itinerary] = []
    for o in q.origins[:2]:
        for d in q.destinations[:2]:
            if o == d:
                continue
            url = search_url(o, d, q.departure, q.return_date, q.adults, q.cabin)
            outs = parse(_fetch(o, d, q.departure, q.adults, q.cabin), o, d, q.max_stops)
            if not q.return_date:
                out += [Itinerary(source="easemytrip", price=p, currency="INR", slices=[sl], booking_url=url,
                                  seller="EaseMyTrip", seller_kind="ota", warnings=[NOTE]) for p, sl, _ in outs[:40]]
                continue
            if not outs:
                continue
            backs = parse(_fetch(d, o, q.return_date, q.adults, q.cabin), d, o, q.max_stops)
            for p1, s1, _ in outs[:6]:
                for p2, s2, _ in backs[:6]:
                    out.append(Itinerary(source="easemytrip", price=round(p1 + p2, 2), currency="INR",
                                         slices=[s1, s2], booking_url=url, seller="EaseMyTrip", seller_kind="ota",
                                         self_transfer=True, warnings=[NOTE, TWO_OW]))
    return sorted(out, key=lambda i: i.price)
