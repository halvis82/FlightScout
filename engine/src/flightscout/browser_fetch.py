"""Google requests from the visitor's own browser (FlightScout extension).

The engine runs the normal Google search code, but in "browser mode" every
Google page fetch is answered from pages the visitor's browser already
fetched (from their own IP). Any page it doesn't have yet is recorded and the
search reports which URLs are still needed; the browser fetches those and
calls again. A one way search takes 1 round, a round trip 2 (outbound list,
then the return pages in parallel).

Pages are passed as the page's ``ds:1`` data (what fli parses), not HTML, to
keep requests small."""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from typing import Any

from fli.search import dates as _fli_dates
from fli.search import flights as _fli_flights

_state: contextvars.ContextVar[dict | None] = contextvars.ContextVar("browser_pages", default=None)
_EMPTY: list = [None] * 8  # parses as "no flights" without raising

_orig = {"flights": _fli_flights.fetch_payload, "dates": _fli_dates.fetch_payload,
         "pm_flights": _fli_flights.parallel_map, "pm_dates": _fli_dates.parallel_map}


def _fetch(module: str):
    def fetch(client: Any, url: str):
        st = _state.get()
        if st is None:
            return _orig[module](client, url)
        page = st["pages"].get(url)
        if page is None:
            st["need"].append(url)
            return _EMPTY
        return page
    return fetch


def _pm(key: str):
    # carry the per request context into fli's worker threads
    def pm(fn, items, *a, **k):
        if _state.get() is None:
            return _orig[key](fn, items, *a, **k)
        ctx = contextvars.copy_context()
        return _orig[key](lambda x: ctx.copy().run(fn, x), items, *a, **k)
    return pm


_fli_flights.fetch_payload = _fetch("flights")
_fli_dates.fetch_payload = _fetch("dates")
_fli_flights.parallel_map = _pm("pm_flights")
_fli_dates.parallel_map = _pm("pm_dates")


class NeedPages(Exception):
    def __init__(self, urls: list[str]):
        super().__init__(f"{len(urls)} pages needed")
        self.urls = urls


@contextmanager
def browser_pages(pages: dict[str, Any]):
    """Run Google code against pages from the visitor's browser. Raises
    NeedPages at the end if anything was missing."""
    from . import cache

    st = {"pages": pages, "need": []}
    token = _state.set(st)
    ctoken = cache.disabled.set(True)
    try:
        yield st
    finally:
        _state.reset(token)
        cache.disabled.reset(ctoken)
    if st["need"]:
        raise NeedPages(list(dict.fromkeys(st["need"])))
