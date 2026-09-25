"""Omio (OTA for trains, buses and flights, mostly Europe) through the shared
real Chrome (see _browser.py). Cloudflare shows plain HTTP clients a
challenge; headless Chrome passes it by itself.

We open omio.com once (the tab is reused), resolve both cities with the
site's own suggester, submit its search form (the same POST the home page
makes) and capture the results JSON its results page loads
(/bff-core-service/search-experience/results/v2). Omio searches city to city
across every mode; we keep the flight cards between the airports asked for.
Omio sells these itself (``isGoEuroBooking``, fares via Travelfusion and
airline connections), so the seller is Omio. About 25 to 50 seconds cold.

One way only: Omio prices each direction on its own and a round trip here
would be two full searches, so round trip queries return nothing. Prices
are in cents, for all passengers.

NOT VERIFIED, off by default: on every search we compared (BER-BCN, USD and
EUR, Sept 2026) the results page showed about 84% of the ``totalPrice`` in
this JSON for the same flight (e.g. $44 shown vs 52.35), and we could not
find the field or rule the page uses. Until that is resolved, search()
returns nothing unless FLIGHTSCOUT_OMIO_UNVERIFIED=1."""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, datetime

from .. import airlines, airports, cache
from ..models import Itinerary, SearchQuery, Segment, Slice
from . import _browser
from ._airline import countries

log = logging.getLogger(__name__)
SITE = "https://www.omio.com"
EUROPE = {
    "AL", "AT", "BA", "BE", "BG", "CH", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GB", "GR", "HR", "HU",
    "IE", "IS", "IT", "LT", "LU", "LV", "ME", "MK", "MT", "NL", "NO", "PL", "PT", "RO", "RS", "SE", "SI", "SK",
    "TR", "UA", "MD",
}

_LOOKUP_JS = """async term => {
  const r = await fetch('/suggester-api/v5/position?term=' + encodeURIComponent(term) + '&locale=en&hierarchical=true');
  const js = await r.json();
  return js.length ? js[0].positionId : null;
}"""

_SUBMIT_JS = """([dep, arr, day, adults, cur]) => {
  const f = document.getElementById('lpsFerret');
  const set = (n, v) => { let e = f.querySelector(`input[name="${n}"]`);
    if (!e) { e = document.createElement('input'); e.type = 'hidden'; e.name = n; f.appendChild(e); } e.value = v; };
  set('departure_fk', String(dep)); set('arrival_fk', String(arr)); set('departure_date', day);
  set('user_currency', cur);
  for (let i = 0; i < adults; i++) set(`passengerages[${i}]`, '26:57:');
  f.submit();
}"""


def available() -> bool:
    return _browser.available()


def relevant(origins: list[str], destinations: list[str]) -> bool:
    if not available():
        return False
    o, d = countries(origins), countries(destinations)
    return bool(o and d and (o | d) <= EUROPE)


def _city(code: str) -> str:
    ap = airports.get(code)
    return ap.city if ap else code


def _fetch(o: str, d: str, day: date, adults: int, currency: str) -> tuple[dict, str]:
    def job(page) -> tuple[str, str]:
        if "omio.com" not in page.url or "/app/search-frontend/" in page.url:
            page.goto(SITE + "/", wait_until="domcontentloaded", timeout=60000)
        if not _browser.pass_cloudflare(page, 30):
            raise RuntimeError("omio: Cloudflare challenge did not clear")
        page.wait_for_selector("#lpsFerret", state="attached", timeout=30000)
        dep = page.evaluate(_LOOKUP_JS, _city(o))
        arr = page.evaluate(_LOOKUP_JS, _city(d))
        if not dep or not arr:
            raise RuntimeError(f"omio: unknown city for {o if not dep else d}")
        got = _browser.capture(
            page, lambda: page.evaluate(_SUBMIT_JS, [dep, arr, f"{day:%d/%m/%Y}", adults, currency.upper()]),
            lambda u: "/search-experience/results/v2" in u and "direction=outbound" in u, timeout=60,
            body=lambda t: '"isLiveSearchDone":true' in t)
        if not got:
            return "", page.url
        return got[-1][1], re.sub(r"/(train|bus|ferry)(?=\?|$)", "/flight", page.url)

    txt, url = _browser.run(job, "omio", timeout=150)
    if not txt:
        raise RuntimeError(f"omio: no results (ended on {url[:80]})")
    return json.loads(txt), url


def _flight(tid: str, company: str | None) -> tuple[str, str | None]:
    """Omio transport ids look like "LH185", "FR 148" or just "7174" (a
    consolidator's seat on another airline): -> (IATA carrier, number)."""
    tid = (tid or "").replace(" ", "").upper()
    if m := re.fullmatch(r"([A-Z0-9]{2})(\d{1,4}[A-Z]?)", tid):
        if not m.group(1).isdigit():
            return m.group(1), m.group(2).lstrip("0") or m.group(2)
    hit = airlines.find(company or "")[:1] if company else []
    return (hit[0]["iata"] if hit else "??"), (tid.lstrip("0") or None) if tid.isdigit() else (tid or None)


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=None)


def parse(data: dict, q: SearchQuery, url: str, currency: str) -> list[Itinerary]:
    """results/v2 JSON -> flight Itineraries between the airports asked for."""
    d = data.get("data") or {}
    ob, ent = d.get("outbounds") or {}, d.get("entities") or {}
    segs, pos, comp = ent.get("segments") or {}, ent.get("positions") or {}, ent.get("companies") or {}
    journeys = ob.get("journeys") or {}
    out: list[Itinerary] = []
    for cid, card in (ob.get("cards") or {}).items():
        if card.get("travelMode") != "flight" or not card.get("isBookable") or card.get("status") != "available":
            continue
        price = card.get("totalPrice") or card.get("price")
        j = journeys.get(cid)
        if not price or not j:
            continue
        ss = []
        for sid in j.get("segmentIds") or []:
            s = segs.get(str(sid))
            if not s or s.get("travelMode") != "flight":
                ss = []
                break
            a, b = pos.get(str(s["departurePositionId"])) or {}, pos.get(str(s["arrivalPositionId"])) or {}
            cname = (comp.get(str(s.get("companyId"))) or {}).get("name")
            carrier, number = _flight(s.get("transportId") or "", cname)
            ss.append(Segment(
                origin=a.get("iataCode") or "???", destination=b.get("iataCode") or "???",
                departure=_dt(s["departureTime"]), arrival=_dt(s["arrivalTime"]), carrier=carrier,
                carrier_name=cname, flight_number=number, duration_min=s.get("duration"),
            ))
        if not ss or ss[0].origin not in q.origins or ss[-1].destination not in q.destinations:
            continue
        sl = Slice(segments=ss, duration_min=max(1, int(card.get("duration") or 1)))
        if q.max_stops is not None and sl.stops > q.max_stops:
            continue
        out.append(Itinerary(
            source="omio", price=round(price / 100, 2), currency=currency.upper(), slices=[sl], booking_url=url,
            seller="Omio", seller_kind="ota",
            warnings=["Sold by Omio (online travel agency), not the airline."],
        ))
    groups: dict[str, list[Itinerary]] = {}  # the same flight from several fare sources
    for i in sorted(out, key=lambda i: i.price):
        k = "|".join(f"{s.origin}{s.departure:%Y%m%d%H%M}{s.destination}" for s in i.slices[0].segments)
        groups.setdefault(k, []).append(i)
    res = []
    for g in groups.values():
        best = g[0]  # the cheapest; borrow a known flight number when its fare source had none
        known = next((x for x in g if all(s.carrier != "??" for s in x.slices[0].segments)), None)
        if known is not best and known is not None:
            for a, b in zip(best.slices[0].segments, known.slices[0].segments):
                a.carrier, a.flight_number = b.carrier, b.flight_number
        res.append(best)
    return res


def enabled() -> bool:
    return os.environ.get("FLIGHTSCOUT_OMIO_UNVERIFIED") == "1"


def search(q: SearchQuery) -> list[Itinerary]:
    if not enabled() or q.return_date or not relevant(q.origins, q.destinations):
        return []
    cur = q.currency.upper()
    out: list[Itinerary] = []
    done: set[tuple[str, str]] = set()
    for o in q.origins[:2]:
        for d in q.destinations[:2]:
            pair = (_city(o), _city(d))
            if o == d or pair in done:  # one city search covers its airports
                continue
            done.add(pair)
            key = f"omio:{pair[0]}:{pair[1]}:{q.departure}:{q.adults}:{cur}"
            if (hit := cache.get(key, ttl=1800)) is None:
                data, url = _fetch(o, d, q.departure, q.adults, cur)
                hit = {"data": data, "url": url}
                cache.put(key, hit)
            out += parse(hit["data"], q, hit["url"], cur)
    return out
