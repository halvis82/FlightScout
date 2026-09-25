"""Multi source search: fan out to every enabled source in parallel, normalize
currency, merge duplicates and wrap each ticket as a Trip."""

from __future__ import annotations

import contextvars
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

from . import airports, fx, sellers
from .models import Itinerary, SearchQuery, SearchResult, Trip
from .models import DatePrice
from .sources import (_browser, condor, flair, google, kiwi, kiwiweb, norse, serpapi, skyairline, skyscanner,
                      vivaaerobus, volaris, volotea, wideroe, wizzair)
from .sources import (allegiant_browser, norwegian_browser, southwest_browser, transavia_browser,
                      vivaaerobus_browser)
from .sources import aerolineas, aeromexico, alaska, arajet, breeze, frontier, jetblue
from .sources import aerlingus, airnewzealand, flysafair, jazeera, jet2, skyexpress, vueling
from .sources import allianceair, biman, fly91_browser, flyarystan, starair
from .sources import nokair, spring
from .sources import agoda, avianca_browser, easemytrip, ita, ixigo_browser, sas_browser, skiplagged
from .sources import (airniugini_browser, bangkokair_browser, linkairways_browser, philippineairlines_browser,
                      vietnamairlines_browser)
from .sources import (aegean_browser, afklm_browser, akasa_browser, etihad_browser, finnair_browser,
                      flydubai_browser, jejuair_browser, level_browser, qatar_browser, spicejet_browser,
                      tap_browser, tigerair_browser, vietjet_browser, virginaustralia_browser, zipair_browser)
from .sources import (avelo_browser, caribbean_browser, caymanairways_browser, porter_browser, united_browser,
                      westjet_browser, wingo_browser)
from .sources import (almosafer, aviasales_browser, booking, cleartrip, edreams, expedia, gotogate, kayakweb,
                      mytrip, opodo, priceline, traveloka, tripcom_browser, wego)

log = logging.getLogger(__name__)

SOURCES = {
    "google": lambda q: _google(q), "kiwi": kiwi.search, "serpapi": serpapi.search, "volaris": volaris.search,
    "wideroe": wideroe.search, "skyairline": skyairline.search, "norse": norse.search,
    "volotea": volotea.search, "condor": condor.search, "flair": flair.search, "kiwiweb": kiwiweb.search,
}

# Airlines that block plain HTTP clients, read through one shared real Chrome
# (sources/_browser.py). Not in the default source list (Vercel has no
# browser): search() adds them by itself wherever Chrome and Playwright are
# installed (local runner, CLI, GitHub tracker) and the query asks for direct
# airline sources. Each one also gates itself on its own network. Set
# FLIGHTSCOUT_BROWSER=0 to turn them off.
BROWSER_SOURCES = {
    "transavia": transavia_browser.search, "norwegian": norwegian_browser.search,
    "southwest": southwest_browser.search, "vivaaerobus": vivaaerobus_browser.search,
    "allegiant": allegiant_browser.search,
    "avelo": avelo_browser.search, "united": united_browser.search, "porter": porter_browser.search,
    "westjet": westjet_browser.search, "caribbean": caribbean_browser.search,
    "caymanairways": caymanairways_browser.search, "wingo": wingo_browser.search,
    "finnair": finnair_browser.search, "afklm": afklm_browser.search, "level": level_browser.search,
    "tap": tap_browser.search, "aegean": aegean_browser.search, "flydubai": flydubai_browser.search,
    "qatar": qatar_browser.search, "etihad": etihad_browser.search, "spicejet": spicejet_browser.search,
    "akasa": akasa_browser.search, "vietjet": vietjet_browser.search, "tigerair": tigerair_browser.search,
    "zipair": zipair_browser.search, "jejuair": jejuair_browser.search,
    "virginaustralia": virginaustralia_browser.search, "fly91": fly91_browser.search,
    "linkairways": linkairways_browser.search, "airniugini": airniugini_browser.search,
    "vietnamairlines": vietnamairlines_browser.search, "philippineairlines": philippineairlines_browser.search,
    "bangkokair": bangkokair_browser.search, "avianca": avianca_browser.search, "sas": sas_browser.search,
}
SOURCES.update(BROWSER_SOURCES)
SOURCES.update({
    "frontier": frontier.search, "breeze": breeze.search, "jetblue": jetblue.search, "alaska": alaska.search,
    "arajet": arajet.search, "aeromexico": aeromexico.search, "aerolineas": aerolineas.search,
    "jet2": jet2.search, "aerlingus": aerlingus.search, "vueling": vueling.search, "skyexpress": skyexpress.search,
    "jazeera": jazeera.search, "flysafair": flysafair.search, "airnewzealand": airnewzealand.search,
    "biman": biman.search, "flyarystan": flyarystan.search, "starair": starair.search,
    "allianceair": allianceair.search, "nokair": nokair.search, "spring": spring.search,
})
# Booking sites (OTAs and metasearch), each verified against its own results
# page. The "otas" group: plain HTTP ones everywhere, the headless Chrome ones
# only where Chrome is installed.
OTAS = {
    "booking": booking.search, "kayakweb": kayakweb.search, "momondo": kayakweb.search_momondo,
    "cheapflights": kayakweb.search_cheapflights, "expedia": expedia.search, "orbitz": expedia.search_orbitz,
    "travelocity": expedia.search_travelocity, "priceline": priceline.search, "wego": wego.search,
    "gotogate": gotogate.search, "mytrip": mytrip.search,
    "skiplagged": skiplagged.search, "easemytrip": easemytrip.search, "agoda": agoda.search,
    # ITA Matrix (Google's fare engine): every airline, real fares, slow (25 to 50 s)
    "ita": ita.search,
}
OTAS_BROWSER = {
    "tripcom": tripcom_browser.search, "aviasales": aviasales_browser.search, "edreams": edreams.search,
    "opodo": opodo.search, "almosafer": almosafer.search, "traveloka": traveloka.search, "cleartrip": cleartrip.search,
    "ixigo": ixigo_browser.search,
}
OTAS_FAST = {"booking", "expedia", "orbitz", "travelocity", "skiplagged", "easemytrip", "gotogate", "mytrip"}
SOURCES.update(OTAS)
SOURCES.update(OTAS_BROWSER)
OTA_WAIT = float(os.environ.get("FLIGHTSCOUT_OTA_WAIT", "45"))
SLOW_WAIT = {"ita": 90.0}  # sources that need longer than OTA_WAIT
# Direct airline sources over plain HTTP. Each gates itself on its network.
AIRLINES = ["volaris", "wideroe", "skyairline", "norse", "volotea", "condor", "flair",
            "frontier", "breeze", "jetblue", "alaska", "arajet", "aeromexico", "aerolineas",
            "jet2", "aerlingus", "vueling", "skyexpress", "jazeera", "flysafair", "airnewzealand",
            "biman", "flyarystan", "starair", "allianceair", "nokair", "spring"]
_DIRECT = set(AIRLINES)


# Turn sources or whole groups off on this deployment, e.g. on the hosted
# engine if it gets limited: FLIGHTSCOUT_DISABLE=otas,kiwi (names or groups:
# airlines, browser, otas). The local runner keeps its own setting.
def _disabled() -> set[str]:
    raw = {x.strip().lower() for x in os.environ.get("FLIGHTSCOUT_DISABLE", "").split(",") if x.strip()}
    out = set(raw)
    if "airlines" in raw:
        out |= set(AIRLINES) | set(BROWSER_SOURCES)
    if "browser" in raw:
        out |= set(BROWSER_SOURCES) | set(OTAS_BROWSER)
    if "otas" in raw:
        out |= set(OTAS) | set(OTAS_BROWSER)
    return out


# A source that answers "blocked" (403, 429, captcha...) is paused instead of
# being hit again on every search, which is what gets IPs banned for longer.
# 10 minutes, doubling on repeat blocks up to an hour. Google has its own
# fallback (SearchAPI/SerpApi) and is not paused.
_BLOCK_WORDS = ("403", "429", "rate_limited", "captcha", "unusual traffic", "access denied", "forbidden",
                "too many requests", "security verification")
_cool: dict[str, tuple[float, float]] = {}  # source -> (paused until, next pause length)


def _cooling(s: str) -> float:
    until = _cool.get(s, (0.0, 0.0))[0]
    return max(0.0, until - time.time())


def _note(s: str, err: Exception | None) -> None:
    if s == "google":
        return
    if err is None:
        _cool.pop(s, None)
    elif any(w in str(err).lower() for w in _BLOCK_WORDS):
        length = _cool.get(s, (0.0, 600.0))[1]
        _cool[s] = (time.time() + length, min(length * 2, 3600.0))
        log.warning("source %s blocked, paused %d min", s, length // 60)


def expand_sources(names: list[str]) -> list[str]:
    """Resolve the "airlines" group (and legacy explicit airline lists) to
    every direct airline source, plus the browser ones where Chrome is here."""
    out = [s for s in names if s in SOURCES and (s != "serpapi" or serpapi.enabled())]
    if "airlines" in names:
        out += [s for s in AIRLINES if s not in out]
    if ("airlines" in names or set(names) & _DIRECT) and _browser.available():
        out += [s for s in BROWSER_SOURCES if s not in out]
    # "otas" = all booking sites; the website asks for them in two parts so the
    # fast ones (answer in 1 to 15 s) show before the slow ones (ITA Matrix,
    # the polling metasearch sites and the browser ones, 20 to 90 s).
    if "otas" in names or "otas_fast" in names:
        out += [s for s in OTAS if s in OTAS_FAST and s not in out]
    if "otas" in names or "otas_slow" in names:
        out += [s for s in OTAS if s not in OTAS_FAST and s not in out]
        if _browser.available():
            out += [s for s in OTAS_BROWSER if s not in out]
    off = _disabled()
    return [s for s in out if s not in off]

# Airline low fare calendars (one way, cheapest fare per day). Each module
# gates itself with relevant(), so only carriers that fly the market are asked.
CALENDARS = {
    "volaris": volaris, "vivaaerobus": vivaaerobus, "wizzair": wizzair, "volotea": volotea,
    "skyairline": skyairline, "flair": flair, "norse": norse,
    "level": level_browser, "flydubai": flydubai_browser,
    # Every route: Kiwi's own per day calendar and Skyscanner's cached month grid.
    "kiwiweb": kiwiweb, "skyscanner": skyscanner,
}


def direct_dates(origin: str, dest: str, start, end, currency: str) -> tuple[list[DatePrice], dict[str, str]]:
    """Every relevant airline calendar for a route, plus per source errors."""
    mods = {n: m for n, m in CALENDARS.items() if m.relevant([origin], [dest])}
    out: list[DatePrice] = []
    errors: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=len(mods) or 1) as ex:
        futs = {n: ex.submit(m.dates, origin, dest, start, end, currency) for n, m in mods.items()}
        for n, f in futs.items():
            try:
                out.extend(f.result())
            except Exception as e:
                log.warning("calendar %s failed: %s", n, e)
                errors[n] = str(e)[:300]
    return out, errors


def cheapest_per_day(rows: list[DatePrice]) -> list[DatePrice]:
    best: dict = {}
    for r in rows:
        k = (r.departure, r.return_date)
        if k not in best or r.price < best[k].price:
            best[k] = r
    return sorted(best.values(), key=lambda r: r.departure)


def to_currency(it: Itinerary, cur: str) -> Itinerary:
    if it.currency.upper() != cur.upper():
        it.price = round(fx.convert(it.price, it.currency, cur), 2)
        it.currency = cur.upper()
    return it


_TRUSTED = {"google", "kiwi", "kiwiweb", "serpapi"}


def _flag_outliers(items: list[Itinerary]) -> list[Itinerary]:
    """A booking site quoting far below what Google, Kiwi or the airline
    itself ask for the very same flights is usually a bait price that grows at
    checkout. Keep it (error fares happen) but say so."""
    ref: dict[str, float] = {}
    for i in items:
        if i.source in _TRUSTED or i.seller_kind == "airline":
            ref[i.flight_key] = min(i.price, ref.get(i.flight_key, i.price))
    for i in items:
        r = ref.get(i.flight_key)
        if i.seller_kind == "ota" and r and i.price < 0.6 * r:
            i.warnings.append(f"Far cheaper than other sellers ({i.price:.0f} vs {r:.0f} {i.currency}) for the same "
                              "flights: check the final price before paying.")
    return items


def merge(items: list[Itinerary]) -> list[Itinerary]:
    """Same flights from the same kind of seller collapse into the cheapest.
    The same flights sold by an OTA and via Google both stay, since they are
    genuinely different purchases."""
    best: dict[tuple, Itinerary] = {}
    for it in items:
        # a hidden city ticket lists only the flights you fly, so it would look
        # like (and replace) the normal ticket for them: keep both
        hidden = any(w.lower().startswith("hidden city") for w in it.warnings)
        k = (it.flight_key, it.seller_kind, hidden)
        if k not in best or it.price < best[k].price:
            best[k] = it
    return sorted(best.values(), key=lambda i: i.price)


def _google_flex(q: SearchQuery) -> list[Itinerary]:
    """Flexible dates on Google: price every date in the window from the
    calendar, then run full searches on the 3 cheapest date combinations."""
    from datetime import date as _date, timedelta

    df, rf = q.departure_flex_days, q.return_flex_days
    tomorrow = _date.today() + timedelta(days=1)
    lo, hi = max(tomorrow, q.departure - timedelta(days=df)), q.departure + timedelta(days=df)
    o, d = q.origins[0], q.destinations[0]
    pairs: list[tuple[float, _date, _date | None]] = []
    if q.return_date:
        base = (q.return_date - q.departure).days
        rlo, rhi = q.return_date - timedelta(days=rf), q.return_date + timedelta(days=rf)
        lengths = sorted({max(1, base + k) for k in range(-(df + rf), df + rf + 1)})
        # keep it bounded: at most 5 trip lengths around the requested one
        lengths = sorted(lengths, key=lambda n: abs(n - base))[:5]
        for n in lengths:
            for dp in google.dates(o, d, lo, hi, q.currency, trip_days=n, cabin=q.cabin):
                r = dp.departure + timedelta(days=n)
                if rlo <= r <= rhi:
                    pairs.append((dp.price, dp.departure, r))
    else:
        pairs = [(dp.price, dp.departure, None) for dp in google.dates(o, d, lo, hi, q.currency, cabin=q.cabin)]
    pairs.sort()
    best = list(dict.fromkeys((p[1], p[2]) for p in pairs))[:3]
    if (q.departure, q.return_date) not in best:
        best.append((q.departure, q.return_date))
    out: list[Itinerary] = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        # the exact dates get the wide (Cheapest tab) search, alternatives a single page
        runs = [ex.submit(contextvars.copy_context().run, google.search,
                          q.model_copy(update={"departure": dr[0], "return_date": dr[1]}), 8,
                          dr == (q.departure, q.return_date)) for dr in best]
        for res in (f.result() for f in runs):
            out.extend(res)
    return out


def _google(q: SearchQuery) -> list[Itinerary]:
    try:
        if q.departure_flex_days or q.return_flex_days:
            return _google_flex(q)
        return google.search(q)
    except Exception as e:
        # Google refusing our IP: fall back to a paid Google Flights API when
        # one is configured (SEARCHAPI_KEY, then SERPAPI_KEY). Free otherwise.
        if "rate_limited" not in str(e) and "429" not in str(e):
            raise
        from .sources import searchapi

        for fallback in (searchapi, serpapi):
            if fallback.enabled():
                log.warning("google blocked, using %s", fallback.__name__.rsplit(".", 1)[-1])
                return fallback.search(q)
        raise


def search(q: SearchQuery, seller_rules: dict[str, str] | None = None) -> SearchResult:
    q = q.model_copy(update={
        "origins": airports.expand_nearby(q.origins, q.nearby_km),
        "destinations": airports.expand_nearby(q.destinations, q.nearby_km),
    })
    srcs = expand_sources(list(q.sources))
    errors: dict[str, str] = {}
    for s in [s for s in srcs if _cooling(s)]:
        errors[s] = f"paused for {_cooling(s) / 60:.0f} min after being blocked"
        srcs.remove(s)
    found: list[Itinerary] = []
    ex = ThreadPoolExecutor(max_workers=len(srcs) or 1)
    # copy_context: browser mode (see browser_fetch.py) must reach the source threads
    futs = {s: ex.submit(contextvars.copy_context().run, SOURCES[s], q) for s in srcs}
    # Booking sites and browser read airlines can be slow (up to a minute or
    # two): don't hold the search
    # for them. Late ones keep running and fill the cache for the next search.
    deadline = time.monotonic() + OTA_WAIT
    for s, f in futs.items():
        try:
            if s in OTAS or s in OTAS_BROWSER or s in BROWSER_SOURCES:
                until = deadline + SLOW_WAIT.get(s, OTA_WAIT) - OTA_WAIT
                found.extend(f.result(timeout=max(0.0, until - time.monotonic())))
            else:
                found.extend(f.result())
            _note(s, None)
        except FutureTimeout:
            errors[s] = f"still searching after {OTA_WAIT:.0f} s (cached for the next search)"
        except Exception as e:  # one source failing must not sink the search
            log.warning("source %s failed: %s", s, e)
            errors[s] = str(e)[:300]
            _note(s, e)
    ex.shutdown(wait=False)
    for i in found:  # round trip "from" prices: remember which return they were for
        if i.return_pending and i.pending_return is None:
            i.pending_return = q.return_date
    items = merge(_flag_outliers([sellers.annotate(to_currency(i, q.currency)) for i in found]))
    trips = [Trip(tickets=[i], total_price=i.price, currency=i.currency, kind="single",
                  risks=list(i.warnings)) for i in items]
    trips = sellers.apply_rules(trips, seller_rules)
    return SearchResult(query=q, trips=trips, errors=errors, google_url=google.search_url(q))
