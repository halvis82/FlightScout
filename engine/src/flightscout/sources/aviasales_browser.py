"""Aviasales (metasearch, the Travelpayouts flagship) live search through the
shared real Chrome (see _browser.py).

tickets-api.aviasales.com sits behind AWS WAF: plain HTTP clients get a
CloudFront 403, and the site's JS earns an ``aws-waf-token`` first. So we
open the site's own results URL headless, let it start the search (we only
rewrite its /search/v2/start body to search the exact airports and currency
asked, as picking an airport in the form does), wait until its own polling
says the search is complete, then fetch the 50 cheapest tickets once from
inside the page with the same headers the page used. Live quotes from 20 to
40 agencies and airlines; about 25 to 45 seconds on a cold browser.

Prices are the agent's price for all passengers (``price_per_person``
false). Unofficial: the schema can change without notice."""

from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime

from .. import cache
from ..models import Itinerary, SearchQuery, Segment, Slice
from . import _browser

log = logging.getLogger(__name__)
SITE = "https://www.aviasales.com"
_CLASS = {"economy": "Y", "premium": "W", "business": "C", "first": "F"}
# gate name endings of agents that are the airline's own website
_AIRLINE_GATES = ("_ta", "_vayant", "_direct", "_airline")

_FETCH_JS = """
async ([url, hdr, sid, limit]) => {
  const h = {...hdr, 'x-origin-cookie': document.cookie};
  for (let i = 0; i < 3; i++) {
    const r = await fetch(url, {method: 'POST', headers: h, credentials: 'include', body: JSON.stringify(
      {limit: limit, price_per_person: false, search_by_airport: true, search_id: sid,
       last_update_timestamp: 0, order: 'cheapest'})});
    if (r.ok) return await r.text();
    await new Promise(r => setTimeout(r, 1500));
  }
  return '';
}
"""


def available() -> bool:
    return _browser.available()


def relevant(origins: list[str], destinations: list[str]) -> bool:
    return available()  # a metasearch: every market


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None, adults: int = 1) -> str:
    """aviasales.com results page: ORIGddmmDEST[ddmm]N."""
    return f"{SITE}/search/{origin}{dep:%d%m}{dest}{f'{ret:%d%m}' if ret else ''}{adults}"


def _directions(o: str, d: str, dep: date, ret: date | None) -> list[dict]:
    dirs = [{"origin": o, "destination": d, "date": dep.isoformat(),
             "is_origin_airport": True, "is_destination_airport": True}]
    if ret:
        dirs.append({"origin": d, "destination": o, "date": ret.isoformat(),
                     "is_origin_airport": True, "is_destination_airport": True})
    return dirs


def _fetch(o: str, d: str, dep: date, ret: date | None, adults: int, cabin: str, currency: str) -> str:
    url = deeplink(o, d, dep, ret, adults)

    def job(page) -> str:
        st: dict = {}
        t0 = time.time()

        def rewrite(route):
            try:
                body = json.loads(route.request.post_data or "{}")
                sp = body.setdefault("search_params", {})
                sp["directions"] = _directions(o, d, dep, ret)
                sp["passengers"] = {"adults": adults, "children": 0, "infants": 0}
                sp["trip_class"] = _CLASS.get(cabin, "Y")
                body["currency_code"] = currency.lower()
                route.continue_(post_data=json.dumps(body))
            except Exception as e:  # never block the page's own search
                log.debug("aviasales rewrite failed: %s", e)
                route.continue_()

        def on_request(rq):
            if "/search/v3.2/results" in rq.url and "hdr" not in st:
                st["hdr"] = {k: v for k, v in rq.headers.items()
                             if k.startswith("x-") or k in ("authorization", "content-type", "accept")}
                st["url"] = rq.url

        def on_response(r):
            try:
                if "/search/v2/start" in r.url and r.ok:
                    st["sid"] = r.json()["search_id"]
                elif "/search/v3.2/results" in r.url and r.ok and "sid" in st:
                    if any(c.get("chunk_id") == "results" and c.get("last_update_timestamp") == 0
                           for c in r.json()):
                        st["done"] = True
            except Exception as e:
                log.debug("aviasales response: %s", e)

        page.route("**/search/v2/start", rewrite)
        page.on("request", on_request)
        page.on("response", on_response)
        try:
            page.goto(url, wait_until="commit", timeout=60000)
            while time.time() - t0 < 100 and "done" not in st:
                page.wait_for_timeout(300)
        finally:
            page.remove_listener("request", on_request)
            page.remove_listener("response", on_response)
            page.unroute("**/search/v2/start")
        if "sid" not in st or "hdr" not in st:
            raise RuntimeError(f"aviasales: search did not start (ended on {page.url[:80]})")
        return page.evaluate(_FETCH_JS, [st["url"], st["hdr"], st["sid"], 50])

    txt = _browser.run(job, "aviasales", timeout=160)
    if not txt:
        raise RuntimeError("aviasales: no results")
    return txt


def _dt(s: str) -> datetime:
    return datetime.strptime(s[:16], "%Y-%m-%d %H:%M")


def parse(chunks: list[dict], q: SearchQuery, url: str) -> list[Itinerary]:
    """/search/v3.2/results chunks -> one Itinerary per ticket at its
    cheapest agent's price."""
    out: list[Itinerary] = []
    for c in chunks:
        legs = c.get("flight_legs") or []
        agents = c.get("agents") or {}
        names = {k: ((v.get("name") or {}).get("en") or {}).get("default") for k, v in (c.get("airlines") or {}).items()}
        for t in c.get("tickets") or []:
            props = [p for p in t.get("proposals") or [] if (p.get("price") or {}).get("value")]
            if not props:
                continue
            p = min(props, key=lambda x: x["price"]["value"])
            slices = []
            for seg in t.get("segments") or []:
                ss = []
                for idx in seg.get("flights") or []:
                    f = legs[idx]
                    mk = ((p.get("flight_terms") or {}).get(str(idx)) or {}).get("marketing_carrier_designator") \
                        or f.get("operating_carrier_designator") or {}
                    ss.append((f, Segment(
                        origin=f["origin"], destination=f["destination"],
                        departure=_dt(f["local_departure_date_time"]), arrival=_dt(f["local_arrival_date_time"]),
                        carrier=mk.get("carrier") or "??", carrier_name=names.get(mk.get("carrier") or ""),
                        flight_number=str(mk.get("number") or "").lstrip("0") or None,
                        duration_min=(f["arrival_unix_timestamp"] - f["departure_unix_timestamp"]) // 60
                        if f.get("arrival_unix_timestamp") else None,
                        aircraft=(f.get("equipment") or {}).get("name"),
                    )))
                if not ss:
                    break
                dur = (ss[-1][0].get("arrival_unix_timestamp", 0) - ss[0][0].get("departure_unix_timestamp", 0)) // 60
                slices.append(Slice(segments=[s for _, s in ss], duration_min=max(1, dur)))
            else:
                if not slices or slices[0].origin not in q.origins or slices[0].destination not in q.destinations:
                    continue
                if q.max_stops is not None and any(s.stops > q.max_stops for s in slices):
                    continue
                ag = agents.get(str(p.get("agent_id"))) or {}
                seller = ((ag.get("label") or {}).get("en") or {}).get("default") or ag.get("gate_name") or "Aviasales"
                kind = "airline" if str(ag.get("gate_name", "")).endswith(_AIRLINE_GATES) else "ota"
                warn = [] if kind == "airline" else [f"Sold by {seller} (online travel agency) via Aviasales."]
                if any(any(tr.get("recheck_baggage") for tr in seg.get("transfers") or [])
                       for seg in t.get("segments") or []):
                    warn.append("Baggage recheck on a connection (separate tickets).")
                out.append(Itinerary(
                    source="aviasales", price=float(p["price"]["value"]),
                    currency=p["price"].get("currency_code", "USD").upper(), slices=slices, booking_url=url,
                    seller=seller, seller_kind=kind,
                    self_transfer=any(any(tr.get("recheck_baggage") for tr in seg.get("transfers") or [])
                                      for seg in t.get("segments") or []),
                    warnings=warn,
                ))
    return sorted(out, key=lambda i: i.price)


def search(q: SearchQuery) -> list[Itinerary]:
    if not available():
        return []
    cur = q.currency.upper()
    out: list[Itinerary] = []
    for o in q.origins[:1]:
        for d in q.destinations[:2]:
            if o == d:
                continue
            key = f"aviasales:{o}:{d}:{q.departure}:{q.return_date}:{q.adults}:{q.cabin}:{cur}"
            if (chunks := cache.get(key, ttl=1800)) is None:
                chunks = json.loads(_fetch(o, d, q.departure, q.return_date, q.adults, q.cabin, cur))
                if any(c.get("tickets") for c in chunks):
                    cache.put(key, chunks)
            out += parse(chunks, q, deeplink(o, d, q.departure, q.return_date, q.adults))
    return out
