"""Shared flow for airlines whose booking app is Amadeus Digital Experience
Suite (DES) and whose own home page starts a search with a form POST
(Bangkok Airways, Vietnam Airlines, Philippine Airlines, ...).

The airline's search box posts ``search`` (JSON: travelers, itineraries,
commercialFareFamilies) and ``portalFacts`` (JSON list of key/value pairs) to
the DES app (``https://booking.<airline>/booking?lang=..``), which then gets an
anonymous token and fetches ``/v2/search/air-bounds`` from api-des.<airline>.
In the shared headless Chrome we open the airline's home page once (the apps
sit behind Imperva, which wants a real referrer), submit the same form and
capture the air-bounds JSON. No keys: the app authenticates itself.

The response has Etihad's shape, so etihad_browser.parse reads it."""

from __future__ import annotations

import json
import logging
from datetime import date
from urllib.parse import urlparse

from .. import cache
from . import _browser
from .etihad_browser import parse  # noqa: F401  (re-exported for the airline modules)

log = logging.getLogger(__name__)
_SUBMIT = """([url, fields]) => { const n = document.createElement('form'); n.method = 'POST'; n.action = url;
  for (const [k, v] of fields) { const i = document.createElement('input'); i.type = 'hidden'; i.name = k;
    i.value = v; n.appendChild(i); }
  document.body.appendChild(n); n.submit(); }"""


def search_fields(o: str, d: str, day: date, adults: int, families: list[str] | None,
                  facts: list[dict] | None) -> list[list[str]]:
    search: dict = {"travelers": [{"passengerTypeCode": "ADT"} for _ in range(adults)],
                    "itineraries": [{"originLocationCode": o, "destinationLocationCode": d,
                                     "departureDateTime": f"{day.isoformat()}T00:00:00.000"}]}
    if families:
        search["commercialFareFamilies"] = families
    fields = [["search", json.dumps(search)]]
    if facts:
        fields.append(["portalFacts", json.dumps(facts)])
    return fields


def fetch(key: str, home: str, book: str, o: str, d: str, day: date, adults: int,
          families: list[str] | None = None, facts: list[dict] | None = None) -> dict:
    """One direction's air-bounds JSON (cached), via the airline's home page.
    ``key`` names the browser tab and the cache entry."""
    ck = f"{key}:{o}:{d}:{day}:{adults}:{','.join(families or [])}"
    if (hit := cache.get(ck)) is not None:
        return hit
    fields = search_fields(o, d, day, adults, families, facts)
    host = urlparse(home).netloc

    def job(page) -> str:
        if urlparse(page.url).netloc != host:
            page.goto(home, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2500)
        got = _browser.capture(page, lambda: page.evaluate(_SUBMIT, [book, fields]),
                               lambda u: "/search/air-bounds" in u, timeout=50,
                               body=lambda t: '"airBoundGroups"' in t or '"errors"' in t)
        blocked = not got and "Access denied" in (page.title() or "") + page.content()[:4000]
        try:  # back to the home page, ready for the next search
            page.goto(home, wait_until="commit", timeout=45000)
        except Exception as e:  # noqa: BLE001
            log.debug("%s: home reload failed: %s", key, e)
        if blocked:
            raise RuntimeError(f"{key}: blocked (Imperva access denied)")
        # the requested bound (the app may also fetch a second, e.g. upsell)
        for _, txt in got:
            try:
                g = (json.loads(txt).get("data") or {}).get("airBoundGroups") or []
            except ValueError:
                continue
            if not g or (g[0].get("boundDetails") or {}).get("originLocationCode") == o:
                return txt
        return got[0][1] if got else ""

    txt = _browser.run(job, key, timeout=150)
    if not txt:
        raise RuntimeError(f"{key}: no availability response (blocked or page changed)")
    data = json.loads(txt)
    if "data" not in data:
        if "errors" in data:  # no flights that day
            data = {"data": {"airBoundGroups": []}}
        else:
            raise RuntimeError(f"{key}: error response {txt[:150]!r}")
    cache.put(ck, data)
    return data
