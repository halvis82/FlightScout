"""Kiwi.com through the GraphQL backend its own website uses
(api.skypicker.com/umbrella/v2/graphql, keyless, Chrome TLS impersonation).

Compared to the public MCP endpoint (kiwi.py) this is much broader and faster:
up to 100 itineraries per call instead of 15, several origins and
destinations in one request, a real "anywhere" explore that returns one
cheapest trip per city (about 80 cities in one call, no region fan out), and a
per day price calendar. Same fares and booking links as kiwi.com itself.

Unofficial: the schema can change without notice. Everything here fails soft
(the caller records the error and the MCP source still runs)."""

from __future__ import annotations

import random
import threading
import time
from datetime import date, datetime, timedelta

from curl_cffi import requests as cr

from .. import airports, cache
from ..models import DatePrice, Destination, Itinerary, SearchQuery, Segment, Slice

URL = "https://api.skypicker.com/umbrella/v2/graphql"
SITE = "https://www.kiwi.com"
_HEADERS = {"Origin": SITE, "Referer": SITE + "/", "Accept": "application/json"}
_CABIN = {"economy": "ECONOMY", "premium": "PREMIUM_ECONOMY", "business": "BUSINESS", "first": "FIRST_CLASS"}
_RETRY = {429, 500, 502, 503, 504}
_slots = threading.BoundedSemaphore(4)
_local = threading.local()

KIWI_WARNING = (
    "Sold by Kiwi.com (online travel agency). Connections between different airlines "
    "are usually separate tickets protected only by the Kiwi Guarantee, not by the airlines."
)

_SEG = ("sectorSegments { segment { code carrier { code name } source { localTime station { code } } "
        "destination { localTime station { code } } duration } layover { isBaggageRecheck isStationChange } }")
_ITIN = ("id price { amount } bookingOptions { edges { node { bookingUrl } } } "
         "bagsInfo { includedCheckedBags includedHandBags } ")
Q_ONEWAY = """query($s: SearchOnewayInput, $f: ItinerariesFilterInput, $o: ItinerariesOptionsInput) {
 onewayItineraries(search: $s, filter: $f, options: $o) { __typename ... on AppError { code message }
  ... on Itineraries { itineraries { ... on ItineraryOneWay { %s sector { duration %s } } } } } }""" % (_ITIN, _SEG)
Q_RETURN = """query($s: SearchReturnInput, $f: ItinerariesFilterInput, $o: ItinerariesOptionsInput) {
 returnItineraries(search: $s, filter: $f, options: $o) { __typename ... on AppError { code message }
  ... on Itineraries { itineraries { ... on ItineraryReturn { %s outbound { duration %s } inbound { duration %s } } } } } }""" % (
    _ITIN, _SEG, _SEG)
_OPC = ("price { amount } departureDate destination { station { code slug city { name } country { code } "
        "gps { lat lng } } }")
Q_OPC_ONEWAY = """query($s: SearchOnewayInput, $f: ItinerariesFilterInput, $o: ItinerariesOptionsInput) {
 onewayOnePerCityItineraries(search: $s, filter: $f, options: $o) { __typename ... on AppError { code message }
  ... on OnePerCityItineraries { itineraries { %s } } } }""" % _OPC
Q_OPC_RETURN = """query($s: SearchReturnInput, $f: ItinerariesFilterInput, $o: ItinerariesOptionsInput) {
 returnOnePerCityItineraries(search: $s, filter: $f, options: $o) { __typename ... on AppError { code message }
  ... on OnePerCityItineraries { itineraries { %s ... on ReturnOnePerCityItinerary { returnDate } } } } }""" % _OPC
Q_CAL = """query($s: SearchPricesCalendarInput, $f: ItinerariesFilterInput, $o: ItinerariesOptionsInput) {
 itineraryPricesCalendar(search: $s, filter: $f, options: $o) { __typename ... on AppError { code message }
  ... on ItineraryPricesCalendar { calendar { date ratedPrice { price { amount } } } } } }"""


def relevant(origins: list[str], destinations: list[str]) -> bool:
    return True  # Kiwi covers every market


def _session() -> cr.Session:
    if not hasattr(_local, "s"):
        _local.s = cr.Session(impersonate="chrome")
    return _local.s


def _gql(query: str, variables: dict, feature: str, ttl: int | None = None) -> dict:
    """Run one query and return the payload of its single root field."""
    import json
    key = "kiwiweb:" + feature + ":" + json.dumps(variables, sort_keys=True)
    if (hit := (cache.get(key, ttl=ttl) if ttl else cache.get(key))) is not None:
        return hit
    last = ""
    for attempt in range(3):
        with _slots:
            r = _session().post(f"{URL}?featureName={feature}", headers=_HEADERS, timeout=45,
                                json={"query": query, "variables": variables})
        if r.status_code in _RETRY:
            last = f"HTTP {r.status_code}"
            time.sleep(min(6, 0.8 * 2 ** attempt) + random.random() * 0.5)
            continue
        r.raise_for_status()
        body = r.json()
        if body.get("errors") and not body.get("data"):
            raise RuntimeError("kiwiweb: " + str(body["errors"][0].get("message"))[:200])
        res = next(iter((body.get("data") or {}).values()), None) or {}
        if res.get("__typename") == "AppError":
            raise RuntimeError(f"kiwiweb: {res.get('code')} {res.get('message')}"[:300])
        cache.put(key, res)
        return res
    raise RuntimeError(f"kiwiweb: Kiwi did not respond ({last})")


def _ids(codes: list[str]) -> dict:
    return {"ids": [f"Station:airport:{c.upper()}" for c in codes]}


def _range(a: date, b: date | None = None) -> dict:
    return {"start": f"{a.isoformat()}T00:00:00", "end": f"{(b or a).isoformat()}T23:59:59"}


def _filter(limit: int = 100, max_stops: int | None = None) -> dict:
    f = {"limit": limit, "allowDifferentStationConnection": True, "enableSelfTransfer": True,
         "enableThrowAwayTicketing": False, "enableTrueHiddenCity": False, "transportTypes": ["FLIGHT"],
         "contentProviders": ["KIWI", "FRESH", "KAYAK"]}
    if max_stops is not None:
        f["maxStopsCount"] = max_stops
    return f


def _options(currency: str) -> dict:
    return {"partner": "skypicker", "currency": currency.lower(), "locale": "en", "sortBy": "PRICE",
            "storeSearch": False}


def _passengers(adults: int, cabin: str = "economy") -> dict:
    return {"passengers": {"adults": adults},
            "cabinClass": {"cabinClass": _CABIN.get(cabin, "ECONOMY"), "applyMixedClasses": False}}


def _slice(sector: dict) -> Slice:
    segs = []
    for ss in sector["sectorSegments"]:
        s = ss["segment"]
        carrier = (s.get("carrier") or {}).get("code") or "??"
        segs.append(Segment(
            origin=s["source"]["station"]["code"], destination=s["destination"]["station"]["code"],
            departure=datetime.fromisoformat(s["source"]["localTime"][:19]),
            arrival=datetime.fromisoformat(s["destination"]["localTime"][:19]),
            carrier=carrier, carrier_name=(s.get("carrier") or {}).get("name"),
            flight_number=str(s.get("code") or "").removeprefix(carrier) or None,
            duration_min=(s["duration"] // 60) if s.get("duration") else None,
        ))
    return Slice(segments=segs, duration_min=max(1, (sector.get("duration") or 60) // 60))


def _self_transfer(sectors: list[dict]) -> bool:
    for sec in sectors:
        segs = sec["sectorSegments"]
        if len({(x["segment"].get("carrier") or {}).get("code") for x in segs}) > 1:
            return True
        if any((x.get("layover") or {}).get("isBaggageRecheck") for x in segs):
            return True
    return False


def _itinerary(it: dict, currency: str) -> Itinerary | None:
    sectors = [it["sector"]] if it.get("sector") else [it.get("outbound"), it.get("inbound")]
    sectors = [s for s in sectors if s]
    if not sectors or not it.get("price"):
        return None
    edges = (it.get("bookingOptions") or {}).get("edges") or []
    url = (edges[0]["node"].get("bookingUrl") or "") if edges else ""
    st = _self_transfer(sectors)
    bags = it.get("bagsInfo") or {}
    return Itinerary(
        source="kiwiweb", price=float(it["price"]["amount"]), currency=currency.upper(),
        slices=[_slice(s) for s in sectors], booking_url=(SITE + url) if url.startswith("/") else (url or SITE),
        seller="Kiwi.com", seller_kind="ota", self_transfer=st,
        baggage={"checked": bags.get("includedCheckedBags"), "hand": bags.get("includedHandBags")} if bags else None,
        warnings=[KIWI_WARNING] if st else ["Sold by Kiwi.com (online travel agency), not the airline."],
    )


def search(q: SearchQuery) -> list[Itinerary]:
    """One request covers every origin/destination pair and the flex window."""
    lo = max(date.today(), q.departure - timedelta(days=min(q.departure_flex_days, 10)))
    hi = q.departure + timedelta(days=min(q.departure_flex_days, 10))
    itin = {"source": _ids(q.origins[:6]), "destination": _ids(q.destinations[:6]),
            "outboundDepartureDate": _range(lo, hi)}
    if q.return_date:
        rf = min(q.return_flex_days, 10)
        itin["inboundDepartureDate"] = _range(q.return_date - timedelta(days=rf), q.return_date + timedelta(days=rf))
    v = {"s": {"itinerary": itin, **_passengers(q.adults, q.cabin)},
         "f": _filter(100, q.max_stops), "o": _options(q.currency)}
    res = _gql(Q_RETURN if q.return_date else Q_ONEWAY, v,
               "SearchReturnItinerariesQuery" if q.return_date else "SearchOneWayItinerariesQuery")
    out = [i for it in res.get("itineraries") or [] if (i := _itinerary(it, q.currency))]
    if q.max_stops is not None:
        out = [i for i in out if all(s.stops <= q.max_stops for s in i.slices)]
    return out


def deeplink(origin: str, dest: str, dep: date, ret: date | None = None) -> str:
    """kiwi.com results page. Kiwi resolves airport codes in the path."""
    tail = f"/{dep.isoformat()}" + (f"/{ret.isoformat()}" if ret else "/no-return")
    return f"{SITE}/en/search/results/{origin.lower()}/{dest.lower()}{tail}"


def explore(origin: str | list[str], start: date, end: date, currency: str,
            nights: tuple[int, int] | None = None, limit: int = 300) -> list[Destination]:
    """Cheapest trip to every city Kiwi sells from ``origin`` (one call, no
    region fan out). With ``nights`` it prices round trips of that length."""
    origins = [origin] if isinstance(origin, str) else list(origin)
    itin = {"source": _ids(origins[:4]), "destination": {"ids": []},
            "outboundDepartureDate": _range(max(start, date.today()), end)}
    if nights:
        itin["nightsCount"] = {"start": nights[0], "end": nights[1]}
    v = {"s": {"itinerary": itin, **_passengers(1)}, "o": _options(currency),
         "f": {**_filter(limit), "allowChangeInboundDestination": True, "allowChangeInboundSource": True}}
    res = _gql(Q_OPC_RETURN if nights else Q_OPC_ONEWAY, v,
               "SearchReturnOnePerCityItinerariesQuery" if nights else "SearchOneWayOnePerCityItinerariesQuery",
               ttl=6 * 3600)
    out = []
    for it in res.get("itineraries") or []:
        st = (it.get("destination") or {}).get("station") or {}
        code, price = st.get("code"), (it.get("price") or {}).get("amount")
        if not code or price is None or not it.get("departureDate"):
            continue
        dep = date.fromisoformat(it["departureDate"][:10])
        ret = date.fromisoformat(it["returnDate"][:10]) if it.get("returnDate") else None
        ap, gps = airports.get(code), st.get("gps") or {}
        out.append(Destination(
            origin=origins[0], destination=code, city=((st.get("city") or {}).get("name")) or (ap.city if ap else None),
            country=((st.get("country") or {}).get("code")) or (ap.country if ap else None),
            price=float(price), currency=currency.upper(), departure=dep, return_date=ret, source="kiwiweb",
            booking_url=deeplink(origins[0], code, dep, ret),
            lat=gps.get("lat") or (ap.lat if ap else None), lon=gps.get("lng") or (ap.lon if ap else None),
        ))
    return out


def dates(origin: str, dest: str, start: date, end: date, currency: str = "USD") -> list[DatePrice]:
    """Cheapest one way Kiwi price per departure day (includes self transfer
    combinations, so it is often below any single airline)."""
    v = {"s": {"source": _ids([origin]), "destination": _ids([dest]),
               "dates": _range(max(start, date.today()), end), **_passengers(1)},
         "f": _filter(), "o": _options(currency)}
    res = _gql(Q_CAL, v, "PriceCalendar", ttl=6 * 3600)
    out = []
    for c in res.get("calendar") or []:
        p = ((c.get("ratedPrice") or {}).get("price") or {}).get("amount")
        if p is None or float(p) <= 0:
            continue
        d = date.fromisoformat(c["date"][:10])
        if start <= d <= end:
            out.append(DatePrice(origin=origin, destination=dest, departure=d, price=float(p),
                                 currency=currency.upper(), source="kiwiweb", booking_url=deeplink(origin, dest, d)))
    return out
