"""ITA Matrix (matrix.itasoftware.com), Google's QPX fare engine, over the
JSON RPC its own web app calls: priced, availability checked itineraries on
every airline sold through the GDSs (not most low cost carriers).

Every call is one POST to content-alkalimatrix-pa.googleapis.com/batch with
the real request wrapped in a multipart/mixed envelope, authorized by the
public API key the web app ships in its gstatic "alkali" bundle. No cookies,
no login. The key is read from the live bundle at runtime (the entry tagged
``matrix``, cached a week) and never stored in the code.

A search is one /v1/search call (15 to 45 seconds: QPX prices the whole
market) returning up to 25 solutions. Connections only come with their
airports there, so for each connecting result we expand the solution with
/v1/summarize (bookingDetails, under a second, it reuses the search session)
to get every segment's times. Prices are the total for all passengers incl.
taxes and carrier surcharges, in the currency asked for (the sales city is
the departure city, as on the site). The booking link reopens the same
result list on matrix.itasoftware.com; Matrix does not sell tickets: book
through the airline or an agency.

Unofficial: fails soft."""

from __future__ import annotations

import base64
import json
import random
import re
import threading
import time
from datetime import datetime

import httpx

from .. import cache
from ..models import Itinerary, SearchQuery, Segment, Slice

HOME = "https://matrix.itasoftware.com"
BATCH = "https://content-alkalimatrix-pa.googleapis.com/batch"
SELLER = "ITA Matrix (book via airline or agency)"
NOTE = ("ITA Matrix price (Google's fare engine): Matrix does not sell tickets, book these exact flights "
        "with the airline or a travel agency.")
_H = ["x-alkali-application-key: applications/matrix", "x-alkali-auth-apps-namespace: alkali_v2",
      "x-alkali-auth-entities-namespace: alkali_v2", "X-Requested-With: XMLHttpRequest"]
_CABIN = {"economy": "COACH", "premium": "PREMIUM-COACH", "business": "BUSINESS", "first": "FIRST"}
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
       "Chrome/140.0.0.0 Safari/537.36")
_KEY_RE = re.compile(r'\.matrix="(AIza[0-9A-Za-z_-]{35})"')
_lock = threading.Lock()
DETAILS = 8  # connecting results expanded per search (one fast call each)


def relevant(origins: list[str], destinations: list[str]) -> bool:
    return True  # every market


def _client() -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(150, connect=20), headers={"User-Agent": _UA})


def api_key(refresh: bool = False) -> str:
    """The web app's public API key, read from its live JS bundle."""
    with _lock:
        if not refresh and (k := cache.get("ita:key", ttl=7 * 86400)):
            return k
        with _client() as c:
            html = c.get(HOME + "/").text
            for src in re.findall(r'src="(//www\.gstatic\.com/alkali/[^"]+\.js)"', html):
                if m := _KEY_RE.search(c.get("https:" + src).text):
                    cache.put("ita:key", m.group(1))
                    return m.group(1)
    raise RuntimeError("ita: Matrix API key not found in the web app bundle")


def _envelope(path: str, key: str, body: dict, bound: str) -> str:
    return "\r\n".join([
        f"--{bound}", "Content-Type: application/http", "Content-Transfer-Encoding: binary",
        f"Content-ID: <{bound}+gapiRequest@googleapis.com>", "", f"POST {path}?key={key}&alt=json", *_H,
        "Content-Type: application/json", "", json.dumps(body), f"--{bound}--", ""])


def unwrap(text: str) -> dict:
    """The multipart response's one JSON object."""
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b < a:
        raise RuntimeError(f"ita: no JSON in the response: {text[:200]!r}")
    return json.loads(text[a:b + 1])


def _call(path: str, body: dict) -> dict:
    last = ""
    for attempt in range(3):
        key = api_key(refresh=attempt > 0 and "key" in last.lower())
        bound = f"batch{random.randint(10 ** 17, 10 ** 18)}"
        with _client() as c:
            r = c.post(f"{BATCH}?%24ct=multipart%2Fmixed%3B%20boundary%3D{bound}",
                       content=_envelope(path, key, body, bound),
                       headers={"Content-Type": "text/plain; charset=UTF-8", "Origin": HOME, "Referer": HOME + "/"})
        if r.status_code in (429, 500, 502, 503):
            last = f"HTTP {r.status_code}"
            time.sleep(1.5 * (attempt + 1))
            continue
        if r.status_code != 200:
            raise RuntimeError(f"ita: HTTP {r.status_code} {r.text[:150]!r}")
        j = unwrap(r.text)
        err = j.get("error")
        if not err:
            return j
        last = str(err.get("message") or err)
        if re.search(r"API key|API_KEY|has not been used", last):
            continue
        if re.search(r"unavailable|try again|temporar|internal", last, re.I):
            time.sleep(1.5 * (attempt + 1))
            continue
        raise RuntimeError(f"ita: {last[:200]}")
    raise RuntimeError(f"ita: no answer ({last[:150]})")


def _slices(q: SearchQuery, origins: list[str], dests: list[str]) -> list[dict]:
    def one(a, b, day):
        return {"origins": a, "destinations": b, "date": day.isoformat(), "dateModifier": {"minus": 0, "plus": 0},
                "isArrivalDate": False, "filter": {"warnings": {"values": []}}, "selected": False}
    out = [one(origins, dests, q.departure)]
    if q.return_date:
        out.append(one(dests, origins, q.return_date))
    return out


def inputs(q: SearchQuery, origins: list[str], dests: list[str]) -> dict:
    """The web app's search inputs (Search exact date, up to 1 extra stop,
    available fares only)."""
    return {"filter": {}, "page": {"current": 1, "size": 25}, "pax": {"adults": q.adults},
            "slices": _slices(q, origins, dests), "firstDayOfWeek": "SUNDAY", "internalUser": False,
            "sliceIndex": 0, "sorts": "default", "cabin": _CABIN.get(q.cabin, "COACH"), "maxLegsRelativeToMin": 1,
            "changeOfAirport": True, "checkAvailability": True, "currency": q.currency.upper()}


def search_url(q: SearchQuery, origins: list[str], dests: list[str], session: str | None = None,
               solution_set: str | None = None) -> str:
    """matrix.itasoftware.com's own results URL; with the session it reopens
    exactly this result list (Matrix does not rerun a URL without one)."""
    ret = q.return_date.isoformat() if q.return_date else ""
    s = {"type": "round-trip" if ret else "one-way", "slices": [{
        "origin": origins, "dest": dests, "dates": {
            "searchDateType": "specific", "departureDate": q.departure.isoformat(), "departureDateType": "depart",
            "departureDateModifier": "0", "departureDatePreferredTimes": [], "returnDate": ret,
            "returnDateType": "depart", "returnDateModifier": "0", "returnDatePreferredTimes": []}}],
        "options": {"cabin": _CABIN.get(q.cabin, "COACH"), "stops": "-1" if q.max_stops is None else str(q.max_stops),
                    "extraStops": "1", "allowAirportChanges": "true", "showOnlyAvailable": "true",
                    "currency": {"displayName": q.currency.upper(), "code": q.currency.upper()}},
        "pax": {"adults": str(q.adults)}}
    if session and solution_set:
        s["solution"] = {"sessionId": session, "yd": True, "wh": solution_set, "Wi": None}
    enc = base64.b64encode(json.dumps(s, separators=(",", ":")).encode()).decode()
    return f"{HOME}/flights?search={enc.replace('=', '%3D')}"


def money(s: str | None) -> tuple[float, str] | None:
    """'USD784.33' -> (784.33, 'USD')."""
    m = re.fullmatch(r"([A-Z]{3})(-?[0-9.]+)", s or "")
    return (float(m.group(2)), m.group(1)) if m else None


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _mins(a: str, b: str) -> int:
    return int((_dt(b) - _dt(a)).total_seconds() // 60)


def _slice_list(sl: dict) -> Slice | None:
    """A nonstop slice from the solution list (connections need details)."""
    fl = sl.get("flights") or []
    if len(fl) != 1 or not (m := re.fullmatch(r"([A-Z0-9]{2})(\d+)", fl[0])):
        return None
    dep, arr = sl["departure"], sl["arrival"]
    seg = Segment(origin=sl["origin"]["code"], destination=sl["destination"]["code"],
                  departure=_dt(dep).replace(tzinfo=None), arrival=_dt(arr).replace(tzinfo=None),
                  carrier=m.group(1), flight_number=m.group(2), duration_min=_mins(dep, arr))
    return Slice(segments=[seg], duration_min=max(1, int(sl.get("duration") or seg.duration_min)))


def _slice_detail(sl: dict) -> Slice:
    segs = []
    for s in sl.get("segments") or []:
        legs = s.get("legs") or []
        segs.append(Segment(
            origin=s["origin"]["code"], destination=s["destination"]["code"],
            departure=_dt(s["departure"]).replace(tzinfo=None), arrival=_dt(s["arrival"]).replace(tzinfo=None),
            carrier=s["carrier"]["code"], carrier_name=s["carrier"].get("shortName"),
            flight_number=str(s["flight"]["number"]), duration_min=s.get("duration") or _mins(s["departure"],
                                                                                            s["arrival"]),
            aircraft=((legs[0].get("aircraft") or {}).get("shortName") if legs else None),
        ))
    return Slice(segments=segs, duration_min=max(1, _mins(sl["departure"], sl["arrival"])))


def parse(data: dict, q: SearchQuery, details: dict[str, dict] | None = None,
          url: str = HOME) -> list[Itinerary]:
    """/v1/search JSON (+ bookingDetails per solution id) -> Itineraries.
    Connecting solutions without details are skipped."""
    details = details or {}
    names = {c["code"]: c.get("shortName") for c in ((data.get("itineraryCarrierList") or {}).get("groups") or [])
             for c in [c.get("label") or {}] if c.get("code")}
    out = []
    for sol in (data.get("solutionList") or {}).get("solutions") or []:
        pm = money((sol.get("ext") or {}).get("totalPrice") or sol.get("displayTotal"))
        if not pm:
            continue
        det = details.get(sol.get("id"))
        if det:
            slices = [_slice_detail(s) for s in det["itinerary"]["slices"]]
        else:
            slices = [_slice_list(s) for s in (sol.get("itinerary") or {}).get("slices") or []]
            if not slices or any(s is None for s in slices):
                continue
            for sl in slices:
                for seg in sl.segments:
                    seg.carrier_name = names.get(seg.carrier)
        if q.max_stops is not None and any(s.stops > q.max_stops for s in slices):
            continue
        out.append(Itinerary(
            source="ita", price=pm[0], currency=pm[1], slices=slices, booking_url=url, seller=SELLER,
            seller_kind="metasearch", warnings=[NOTE],
        ))
    return out


def _needs_detail(sol: dict) -> bool:
    return any(len(s.get("flights") or []) != 1 for s in (sol.get("itinerary") or {}).get("slices") or [])


def search(q: SearchQuery) -> list[Itinerary]:
    origins, dests = q.origins[:3], [d for d in q.destinations[:3] if d not in q.origins[:3]]
    if not dests:
        return []
    inp = inputs(q, origins, dests)
    key = "ita:" + json.dumps(inp, sort_keys=True)
    if (hit := cache.get(key, ttl=20 * 60)) is None:
        data = _call("/v1/search", {
            "summarizers": ["currencyNotice", "solutionList", "itineraryCarrierList"], "inputs": inp,
            "summarizerSet": "wholeTrip", "name": "specificDatesSlice"})
        sols = (data.get("solutionList") or {}).get("solutions") or []
        details: dict[str, dict] = {}
        for sol in [s for s in sols if _needs_detail(s)][:DETAILS]:
            try:
                d = _call("/v1/summarize", {
                    "summarizers": ["bookingDetails"],
                    "inputs": dict(inp, solution=f"{data['solutionSet']}/{sol['id']}"),
                    "summarizerSet": "viewDetails", "solutionSet": data["solutionSet"], "session": data["session"]})
                if d.get("bookingDetails"):
                    details[sol["id"]] = d["bookingDetails"]
            except Exception:
                continue  # that one result is skipped
        hit = {"data": data, "details": details}
        cache.put(key, hit)
    data = hit["data"]
    url = search_url(q, origins, dests, data.get("session"), data.get("solutionSet"))
    return sorted(parse(data, q, hit["details"], url), key=lambda i: i.price)
