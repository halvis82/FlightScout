"""Currency conversion using ECB reference rates (frankfurter.dev, free, no key).
Rates are cached on disk for 12 hours."""

from __future__ import annotations

import httpx

from . import cache

SUPPORTED = ["NOK", "EUR", "USD", "GBP", "MXN"]


def rates(base: str = "EUR") -> dict[str, float]:
    key = f"fx:{base}"
    hit = cache.get(key, ttl=12 * 3600)
    if hit:
        return hit
    r = httpx.get(f"https://api.frankfurter.dev/v1/latest?base={base}", timeout=15)
    r.raise_for_status()
    data = r.json()["rates"]
    data[base] = 1.0
    cache.put(key, data)
    return data


def convert(amount: float, frm: str, to: str) -> float:
    frm, to = frm.upper(), to.upper()
    if frm == to:
        return amount
    rt = rates("EUR")
    return amount / rt[frm] * rt[to]
