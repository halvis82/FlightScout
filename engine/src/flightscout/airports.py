"""Airport lookup, metro groups and geometry used for hub selection and maps."""

from __future__ import annotations

import json
import math
from functools import lru_cache
from importlib import resources

from pydantic import BaseModel


class Airport(BaseModel):
    iata: str
    name: str
    city: str
    country: str
    lat: float
    lon: float
    size: str  # "L" large, "M" medium


# Metro codes expand to every commercial airport in the area. Searching a
# metro instead of a single airport is usually where the cheap fares hide.
METROS: dict[str, list[str]] = {
    "NYC": ["JFK", "EWR", "LGA"],
    "LON": ["LHR", "LGW", "STN", "LTN", "LCY", "SEN"],
    "PAR": ["CDG", "ORY", "BVA"],
    "TYO": ["HND", "NRT"],
    "CHI": ["ORD", "MDW"],
    "WAS": ["IAD", "DCA", "BWI"],
    "MIL": ["MXP", "LIN", "BGY"],
    "ROM": ["FCO", "CIA"],
    "STO": ["ARN", "BMA", "NYO"],
    "OSLX": ["OSL", "TRF", "RYG"],
    "BAY": ["SFO", "OAK", "SJC"],
    "LAXX": ["LAX", "BUR", "LGB", "SNA", "ONT"],
    "MEX": ["MEX", "NLU"],
    "SEL": ["ICN", "GMP"],
    "SAO": ["GRU", "CGH", "VCP"],
    "BUE": ["EZE", "AEP"],
    "YTO": ["YYZ", "YTZ"],
    "YMQ": ["YUL"],
    "MIA": ["MIA", "FLL"],
    "HOU": ["IAH", "HOU"],
    "DFW": ["DFW", "DAL"],
    "BKK": ["BKK", "DMK"],
    "SHA": ["PVG", "SHA"],
    "BJS": ["PEK", "PKX"],
    "IST": ["IST", "SAW"],
}

# Airports that work well as connection points for self transfer and stopover
# plans: big hubs plus low cost carrier bases with lots of cheap departures.
HUBS: list[str] = [
    # Europe
    "LHR", "LGW", "STN", "CDG", "ORY", "AMS", "FRA", "MUC", "ZRH", "VIE", "CPH",
    "ARN", "OSL", "HEL", "KEF", "DUB", "MAD", "BCN", "LIS", "FCO", "MXP", "BGY",
    "BER", "WAW", "BUD", "IST", "ATH", "BRU", "GDN", "KRK", "MAN", "EDI", "PMI",
    # North America
    "JFK", "EWR", "BOS", "IAD", "ORD", "ATL", "MIA", "FLL", "DFW", "IAH", "DEN",
    "LAX", "SFO", "SEA", "LAS", "PHX", "YYZ", "YUL", "YVR", "MCO", "MSP", "DTW",
    "CLT", "PHL", "SLC", "MEX", "CUN", "GDL", "TIJ",
    # Middle East, Asia, Oceania
    "DXB", "DOH", "AUH", "SIN", "HKG", "BKK", "KUL", "ICN", "NRT", "HND", "TPE",
    "DEL", "BOM", "SYD", "MEL", "AKL",
    # Latin America, Africa
    "BOG", "LIM", "GRU", "EZE", "SCL", "PTY", "JNB", "CAI", "ADD", "NBO", "CMN",
]

GATEWAYS = {
    "LHR", "LGW", "CDG", "AMS", "FRA", "MUC", "CPH", "ARN", "KEF", "DUB", "MAD",
    "BCN", "IST", "FCO", "JFK", "EWR", "BOS", "IAD", "ORD", "ATL", "MIA", "DFW",
    "LAX", "SFO", "SEA", "YYZ", "YVR", "MEX", "DXB", "DOH", "SIN", "HKG", "ICN",
    "NRT", "HND", "BKK", "SYD", "GRU", "BOG", "PTY",
}


@lru_cache
def _db() -> dict[str, Airport]:
    raw = json.loads(
        resources.files("flightscout.data").joinpath("airports.json").read_text("utf-8")
    )
    return {r["iata"]: Airport(**r) for r in raw}


def get(code: str) -> Airport | None:
    return _db().get(code.upper())


def all_airports() -> list[Airport]:
    return list(_db().values())


def _fold(s: str) -> str:
    import unicodedata

    return "".join(c for c in unicodedata.normalize("NFKD", s.lower()) if not unicodedata.combining(c))


def find(query: str, limit: int = 25) -> list[Airport]:
    """Airports matching a code, city or name, accent insensitive
    ("cancun" finds Cancún). Exact codes first, then large airports."""
    q = _fold(query.strip())
    hits = [a for a in _db().values()
            if q == a.iata.lower() or q in _fold(a.city) or q in _fold(a.name)]
    hits.sort(key=lambda a: (a.iata.lower() != q, not _fold(a.city).startswith(q), a.size != "L"))
    return hits[:limit]


def expand(codes: list[str] | str) -> list[str]:
    """Turn "NYC,OSL" or ["NYC","OSL"] into concrete airport codes."""
    if isinstance(codes, str):
        codes = [c for c in codes.replace(" ", "").split(",") if c]
    out: list[str] = []
    for c in codes:
        c = c.upper()
        for a in METROS.get(c, [c]):
            if a not in out:
                out.append(a)
    return out


# Airports that are closer in practice than the map suggests. TIJ is reachable
# from San Diego through the Cross Border Xpress bridge (you walk across from
# a terminal on the US side).
LINKED: dict[str, list[str]] = {
    "SAN": ["TIJ"],
    "TIJ": ["SAN"],
}


def nearby(code: str, radius_km: float, include_medium: bool = True) -> list[str]:
    """Airports with scheduled service within ``radius_km`` of ``code``,
    nearest first, plus hand curated links like SAN and TIJ."""
    base = get(code)
    if not base or radius_km <= 0:
        return []
    hits = []
    for a in _db().values():
        if a.iata == base.iata or (a.size != "L" and not include_medium):
            continue
        d = haversine_km(base.iata, a.iata)
        if d <= radius_km:
            hits.append((d, a.iata))
    hits.sort()
    out = [c for _, c in hits]
    for c in LINKED.get(base.iata, []):
        if c not in out:
            out.insert(0, c)
    return out


def expand_nearby(codes: list[str], radius_km: float, limit: int = 6) -> list[str]:
    """Expand metros, then add nearby airports around each code (capped)."""
    base = expand(codes)
    out = list(base)
    for c in base:
        for n in nearby(c, radius_km):
            if n not in out and len(out) < len(base) + limit:
                out.append(n)
    return out


def haversine_km(a: str, b: str) -> float:
    pa, pb = get(a), get(b)
    if not pa or not pb:
        return float("inf")
    r = 6371.0
    la1, lo1, la2, lo2 = map(math.radians, (pa.lat, pa.lon, pb.lat, pb.lon))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def candidate_hubs(origin: str, destination: str, limit: int = 12, max_detour: float = 1.35,
                   extra: list[str] | None = None) -> list[str]:
    """Hubs that sit roughly on the way. ``max_detour`` is the allowed ratio of
    (origin to hub to destination) over the direct distance. Hubs closest to
    the direct line come first, and ``extra`` hubs (user favorites) are always
    considered when within the detour budget."""
    direct = haversine_km(origin, destination)
    if not math.isfinite(direct) or direct == 0:
        return []
    pool = list(dict.fromkeys((extra or []) + HUBS))
    scored = []
    for h in pool:
        if h in (origin, destination) or not get(h):
            continue
        d1, d2 = haversine_km(origin, h), haversine_km(h, destination)
        # ignore hubs that are basically at the origin or destination
        if d1 < 150 or d2 < 150:
            continue
        ratio = (d1 + d2) / direct
        if ratio <= max_detour or (extra and h in extra and ratio <= max_detour * 1.3):
            scored.append((ratio, h))
    # Big gateways get a bonus since they have far more (and cheaper) long haul
    # options than the geometry alone suggests.
    scored = [(r - (0.2 if h in GATEWAYS else 0), h) for r, h in scored]
    scored.sort()
    # Spread picks along the route (near origin, middle, near destination) so
    # we don't only try hubs clustered at one end.
    buckets: list[list[str]] = [[], [], []]
    for _, h in scored:
        frac = haversine_km(origin, h) / (haversine_km(origin, h) + haversine_km(h, destination))
        buckets[min(2, int(frac * 3))].append(h)
    picked: list[str] = [h for h in (extra or []) if any(h == x for _, x in scored)]
    i = 0
    while len(picked) < limit and any(i < len(b) for b in buckets):
        for b in buckets:
            if i < len(b) and b[i] not in picked and len(picked) < limit:
                picked.append(b[i])
        i += 1
    return picked
