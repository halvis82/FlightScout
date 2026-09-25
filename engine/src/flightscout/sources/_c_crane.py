"""Shared client for airlines on Hitit Crane IBE, a server rendered booking
engine: FlyArystan and Star Air use it (PIA too, behind Cloudflare).

Plain HTTP GET of the booking app's own results page
(``/ibe/availability?depPort=..&arrPort=..&departureDate=dd.mm.yyyy``), the
same URL the airline's search form opens. No API key, no JS. Some hosts only
answer the results page within a session, so the session opens
``/ibe/search`` first (a cookie, like a visitor landing on the form).

Each flight is a ``<div class="js-journey" data-journeyType="OUTBOUND|INBOUND"
data-stop-count=.. data-journey-duration=..>`` block with times, dates,
flight numbers and one ``offer-info-block cabin-name-<BRAND>`` per fare
column, each with its price. The prices are per passenger incl. taxes: the
page's TOTAL (after picking the cheapest bundle) is that price x adults.

Connections: the page names the flights ("FS 7103 - FS 7326") but not the
connecting airport or times (those come from a separate flight info popup),
so only nonstop flights are returned."""

from __future__ import annotations

import re
import threading
from datetime import date, datetime

import certifi
from curl_cffi import requests as cr

from .. import cache

_lock = threading.Lock()
_sessions: dict[str, cr.Session] = {}
_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                       "dec"), 1)}


def _num(s: str) -> float | None:
    s = re.sub(r"[\s  ]", "", s or "")
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", "") if re.search(r",\d{3}$", s) else s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _day(s: str) -> date | None:
    s = s.strip()
    if m := re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", s):
        return date(int(m[3]), int(m[2]), int(m[1]))
    if m := re.fullmatch(r"(\d{1,2})\s+([A-Za-z]{3})[a-z]*\s+(\d{4})", s):
        mo = _MONTHS.get(m[2].lower())
        return date(int(m[3]), mo, int(m[1])) if mo else None
    return None


def _cabin_of(brand: str) -> str:
    b = brand.upper()
    if "FIRST" in b:
        return "first"
    if "PREMIUM" in b or "EXECUTIVE_ECONOMY" in b:
        return "premium"
    if "BUSINESS" in b or "EXECUTIVE" in b:
        return "business"
    return "economy"


def parse(html: str, adults: int = 1, cabin: str = "economy", origin: str | None = None,
          dest: str | None = None) -> dict[str, list[dict]]:
    """Results page -> {"OUTBOUND": [journey, ...], "INBOUND": [...]} with the
    cheapest brand in ``cabin`` per nonstop flight, priced for all
    passengers (see _airline.py for the journey dict). ``origin``/``dest``
    name the airports when the page shows only city names."""
    out: dict[str, list[dict]] = {"OUTBOUND": [], "INBOUND": []}
    currency = None
    blocks = re.split(r'<div[^>]*class="js-journey"', html)[1:]
    for blk in blocks:
        head = blk[:600]
        jt = (re.search(r'data-journeyType="(\w+)"', head) or [None, "OUTBOUND"])[1].upper()
        stops = int((re.search(r'data-stop-count="(\d+)"', head) or [None, "0"])[1])
        dur = re.search(r'data-journey-duration="(\d+)"', head)
        fn = next((x.strip() for x in re.findall(r'class="flight-no"[^>]*>\s*([^<]*?)\s*<', blk) if x.strip()), "")
        nums = re.findall(r"([A-Z0-9]{2})\s*-?\s*(\d{1,5})", fn)
        times = re.findall(r'class="time"[^>]*>\s*(\d{1,2}:\d{2})', blk)[:2]
        days = [_day(x) for x in re.findall(r'class="date"[^>]*>\s*([^<]+?)\s*<', blk)[:2]]
        ports = re.findall(r'class="port"[^>]*>\s*([^<]+?)\s*<', blk)[:2]
        codes = [(re.search(r"\(([A-Z]{3})\)", p) or [None, None])[1] for p in ports]
        if stops or len(nums) != 1 or len(times) < 2 or len(days) < 2 or not all(days):
            continue
        o = codes[0] if codes and codes[0] else (origin if jt == "OUTBOUND" else dest)
        d = codes[1] if len(codes) > 1 and codes[1] else (dest if jt == "OUTBOUND" else origin)
        if not o or not d:
            continue
        fares = []
        for m in re.finditer(r'offer-info-block\s+cabin-name-([^"]+?)\s*"', blk):
            tail = blk[m.end():m.end() + 3000]
            nxt = tail.find("offer-info-block")
            tail = tail if nxt < 0 else tail[:nxt]
            pm = re.search(r'class="\s*price(?:-best-offer)?\s*"[^>]*>\s*([\d][\d,.\s  ]*)<', tail)
            cm = re.search(r'class="\s*currency(?:-best-offer)?\s*"[^>]*>\s*([A-Z]{3})\s*<', tail)
            if pm and (p := _num(pm[1])):
                fares.append((p, m[1].strip()))
                currency = cm[1] if cm else currency
        fares = [f for f in fares if _cabin_of(f[1]) == cabin]
        if not fares:
            continue
        price, brand = min(fares)
        dep = datetime.combine(days[0], datetime.strptime(times[0], "%H:%M").time())
        arr = datetime.combine(days[1], datetime.strptime(times[1], "%H:%M").time())
        minutes = int(dur[1]) // 60 if dur else None
        out.setdefault(jt, []).append({
            "segments": [{"origin": o, "destination": d, "departure": dep.isoformat(), "arrival": arr.isoformat(),
                          "carrier": nums[0][0], "number": nums[0][1], "duration": minutes}],
            "total": round(price * adults, 2), "fare": brand, "duration": minutes, "currency": currency,
        })
    return out


class Crane:
    def __init__(self, key: str, host: str, warm: bool = False):
        self.key = key  # cache namespace, e.g. "flyarystan"
        self.host = host  # e.g. "https://kzr-ports.hosting.aero"
        self.warm = warm  # open /ibe/search first for a session cookie

    def _s(self) -> cr.Session:
        with _lock:
            s = _sessions.get(self.key)
            if s is None:
                # certifi: some Crane hosts send a chain the system store rejects
                s = _sessions[self.key] = cr.Session(impersonate="chrome", verify=certifi.where())
                if self.warm:
                    s.get(f"{self.host}/ibe/search", timeout=30)
            return s

    def params(self, o: str, d: str, dep: date, ret: date | None, adults: int) -> dict:
        p = {"depPort": o, "arrPort": d, "departureDate": f"{dep:%d.%m.%Y}", "adult": str(adults), "child": "0",
             "infant": "0", "tripType": "ROUND_TRIP" if ret else "ONE_WAY", "lang": "en"}
        if ret:
            p["returnDate"] = f"{ret:%d.%m.%Y}"
        return p

    def url(self, o: str, d: str, dep: date, ret: date | None, adults: int, host: str | None = None) -> str:
        return f"{host or self.host}/ibe/availability?" + "&".join(
            f"{k}={v}" for k, v in self.params(o, d, dep, ret, adults).items())

    def fetch(self, o: str, d: str, dep: date, ret: date | None, adults: int) -> str:
        ck = f"crane:{self.key}:{o}:{d}:{dep}:{ret}:{adults}"
        if (hit := cache.get(ck)) is not None:
            return hit
        r = self._s().get(f"{self.host}/ibe/availability", params=self.params(o, d, dep, ret, adults), timeout=45)
        r.raise_for_status()
        html = r.text
        if "js-journey" not in html and "availability-flight-table" not in html:
            if "Just a moment" in html or "Security Check" in html or "Pardon Our Interruption" in html:
                raise RuntimeError(f"{self.key}: blocked by the bot check")
            if "/ibe/search" in str(r.url):  # bounced to the search form: no such route or date
                html = ""
            else:
                raise RuntimeError(f"{self.key}: unexpected page {r.url}")
        # keep only the flight blocks: the full page is 0.3 to 0.7 MB
        i = html.find("availability-flight-table")
        small = html[max(i - 200, 0):] if i >= 0 else ""
        cache.put(ck, small)
        return small
