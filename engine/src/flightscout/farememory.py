"""Fare memory: the cheapest one way price seen per route and day, from every
search this engine runs. The planner uses it to find promising layovers
without asking any site ("a Rome to Oslo leg was 46 USD yesterday").

Kept in a small SQLite file next to the cache, for a week. Best effort: a
read only filesystem (serverless) just means nothing is remembered."""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from datetime import date

from . import cache, fx
from .models import Itinerary

log = logging.getLogger(__name__)

KEEP_S = 7 * 86400
_lock = threading.Lock()
_conn: sqlite3.Connection | None = None
_broken = False


def _db() -> sqlite3.Connection | None:
    global _conn, _broken
    if _conn or _broken:
        return _conn
    try:
        cache.DIR.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(cache.DIR / "fares.sqlite", check_same_thread=False, timeout=5)
        c.execute("""CREATE TABLE IF NOT EXISTS fares (
            origin TEXT, dest TEXT, day TEXT, usd REAL, source TEXT, seen REAL,
            PRIMARY KEY (origin, dest, day, source))""")
        c.execute("DELETE FROM fares WHERE seen < ?", (time.time() - KEEP_S,))
        c.commit()
        _conn = c
    except (OSError, sqlite3.Error) as e:
        log.info("fare memory off: %s", e)
        _broken = True
    return _conn


def record(items: list[Itinerary]) -> None:
    """Remember one way, single slice tickets (the only prices that belong to
    exactly one route and day)."""
    rows = []
    now = time.time()
    for i in items:
        if len(i.slices) != 1 or i.return_pending or i.price <= 0:
            continue
        sl = i.slices[0]
        try:
            usd = fx.convert(i.price, i.currency, "USD")
        except Exception:
            continue
        rows.append((sl.origin, sl.destination, sl.departure.date().isoformat(), round(usd, 2), i.source, now))
    if not rows:
        return
    with _lock:
        c = _db()
        if not c:
            return
        try:
            # keep the cheaper of the old and new price per source and day
            c.executemany("""INSERT INTO fares VALUES (?,?,?,?,?,?)
                ON CONFLICT(origin, dest, day, source) DO UPDATE SET usd = excluded.usd, seen = excluded.seen""", rows)
            c.commit()
        except sqlite3.Error as e:
            log.info("fare memory write failed: %s", e)


def cheapest(origin: str, dest: str, lo: date, hi: date) -> float | None:
    """Cheapest remembered USD price from origin to dest departing lo..hi."""
    with _lock:
        c = _db()
        if not c:
            return None
        try:
            row = c.execute("SELECT MIN(usd) FROM fares WHERE origin=? AND dest=? AND day BETWEEN ? AND ? AND seen > ?",
                            (origin, dest, lo.isoformat(), hi.isoformat(), time.time() - KEEP_S)).fetchone()
        except sqlite3.Error:
            return None
    return row[0] if row and row[0] is not None else None


def from_origin(origin: str, lo: date, hi: date) -> dict[str, float]:
    """Cheapest remembered USD price to every destination seen from origin."""
    return _grouped("SELECT dest, MIN(usd) FROM fares WHERE origin=? AND day BETWEEN ? AND ? AND seen > ? GROUP BY dest",
                    origin, lo, hi)


def to_dest(dest: str, lo: date, hi: date) -> dict[str, float]:
    """Cheapest remembered USD price from every origin seen to dest."""
    return _grouped("SELECT origin, MIN(usd) FROM fares WHERE dest=? AND day BETWEEN ? AND ? AND seen > ? GROUP BY origin",
                    dest, lo, hi)


def _grouped(sql: str, code: str, lo: date, hi: date) -> dict[str, float]:
    with _lock:
        c = _db()
        if not c:
            return {}
        try:
            return dict(c.execute(sql, (code, lo.isoformat(), hi.isoformat(), time.time() - KEEP_S)).fetchall())
        except sqlite3.Error:
            return {}
