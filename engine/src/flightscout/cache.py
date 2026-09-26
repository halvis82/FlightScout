"""Tiny JSON disk cache so repeated searches (and the planner, which fans out
to many legs) do not hammer the sources."""

from __future__ import annotations

import contextvars
import hashlib
import json
import os
import random
import time
from pathlib import Path
from typing import Any

DIR = Path(os.environ.get("FLIGHTSCOUT_CACHE", Path.home() / ".cache" / "flightscout"))
# Off inside browser mode: those searches run against partial pages until the
# browser has fetched everything, so nothing from them may be cached.
disabled: contextvars.ContextVar[bool] = contextvars.ContextVar("cache_disabled", default=False)

DEFAULT_TTL = int(os.environ.get("FLIGHTSCOUT_CACHE_TTL", 30 * 60))


def _path(key: str) -> Path:
    return DIR / (hashlib.sha1(key.encode()).hexdigest() + ".json")


def get(key: str, ttl: int = DEFAULT_TTL) -> Any | None:
    if os.environ.get("FLIGHTSCOUT_NO_CACHE") or disabled.get():
        return None
    p = _path(key)
    try:
        if time.time() - p.stat().st_mtime > ttl:
            return None
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def put(key: str, value: Any) -> None:
    if disabled.get():
        return
    try:
        DIR.mkdir(parents=True, exist_ok=True)
        _path(key).write_text(json.dumps(value, default=str))
    except OSError:
        return  # read only filesystem (serverless), caching is best effort
    if random.random() < 1 / 300:
        prune()


MAX_AGE_S = 10 * 86400  # longer than any TTL in use (rates are refreshed twice a day)
MAX_BYTES = 200 * 1024 * 1024


def prune() -> None:
    """Drop entries nobody can use any more, then the oldest ones while the
    cache is over its size cap."""
    try:
        files = [(p.stat().st_mtime, p.stat().st_size, p) for p in DIR.glob("*.json")]
    except OSError:
        return
    now = time.time()
    keep = []
    for mtime, size, p in files:
        if now - mtime > MAX_AGE_S:
            p.unlink(missing_ok=True)
        else:
            keep.append((mtime, size, p))
    total = sum(size for _, size, _ in keep)
    for mtime, size, p in sorted(keep):
        if total <= MAX_BYTES:
            break
        p.unlink(missing_ok=True)
        total -= size
