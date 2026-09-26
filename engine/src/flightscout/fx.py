"""Currency conversion using ECB reference rates (frankfurter.dev, free, no key).
Rates are cached on disk for 12 hours."""

from __future__ import annotations

import threading
import time

from . import cache

SUPPORTED = ["NOK", "EUR", "USD", "GBP", "MXN"]


# In memory first: a search converts hundreds of prices, and the disk cache
# (off entirely in browser mode) would mean a file read, or an HTTP call, each.
_TTL = 12 * 3600
_mem: dict[str, tuple[float, dict[str, float]]] = {}
_lock = threading.Lock()


def _cached(key: str, fetch) -> dict[str, float]:
    hit = _mem.get(key)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1]
    with _lock:  # one fetch even when many threads convert at once
        hit = _mem.get(key)
        if hit and time.time() - hit[0] < _TTL:
            return hit[1]
        data = cache.get(key, ttl=_TTL)
        if not data:
            try:
                data = fetch()
                cache.put(key, data)
            except Exception:
                # the rate service is down: yesterday's rates beat failing the search
                data = cache.get(key, ttl=30 * 86400)
                if not data:
                    raise
        _mem[key] = (time.time(), data)
        return data


def rates(base: str = "EUR") -> dict[str, float]:
    def fetch():
        import httpx

        r = httpx.get(f"https://api.frankfurter.dev/v1/latest?base={base}", timeout=15)
        r.raise_for_status()
        data = r.json()["rates"]
        data[base] = 1.0
        return data

    return _cached(f"fx:{base}", fetch)


def _wide_rates() -> dict[str, float]:
    """EUR based rates for currencies the ECB does not publish (CLP, PEN,
    ARS, COP...), from open.er-api.com (free, no key, daily)."""
    def fetch():
        import httpx

        r = httpx.get("https://open.er-api.com/v6/latest/EUR", timeout=15)
        r.raise_for_status()
        return r.json()["rates"]

    return _cached("fx-wide:EUR", fetch)


def convert(amount: float, frm: str, to: str) -> float:
    frm, to = frm.upper(), to.upper()
    if frm == to:
        return amount
    rt = rates("EUR")
    if frm not in rt or to not in rt:
        rt = {**_wide_rates(), **rt}
    for c in (frm, to):
        if c not in rt:
            raise ValueError(f"unknown currency {c}")
    return amount / rt[frm] * rt[to]


def known(code: str) -> bool:
    try:
        convert(1.0, "EUR", code)
        return True
    except ValueError:
        return False
