"""One shared real Chrome per process for the airline sources that block plain
HTTP clients (Cloudflare, Akamai, ...).

We start the installed Google Chrome ourselves (no Playwright launch flags,
so no ``--enable-automation`` or ``navigator.webdriver``) and attach over CDP.
Playwright's sync API is bound to the thread that started it, so browser jobs
run on worker threads, up to TABS at once, each with its own connection to the
same Chrome (headless; a headful one only with FLIGHTSCOUT_HEADFUL=1, moved off
screen and minimized). Each job key (one per airline) gets its own page (tab),
reused across searches, so cookies and bot manager tokens earned on the first
search carry over to the next (all pages share the profile's default context:
Cloudflare is stricter with new ones).

Chrome is started lazily on the first job and closed after a few idle
minutes, or at exit."""

from __future__ import annotations

import atexit
import logging
import os
from collections import OrderedDict
import platform
import queue
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from concurrent.futures import Future
from typing import Any, Callable

log = logging.getLogger(__name__)
IDLE_S = int(os.environ.get("FLIGHTSCOUT_BROWSER_IDLE", 300))
_MAC_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def chrome_path() -> str | None:
    for p in (os.environ.get("FLIGHTSCOUT_CHROME"), _MAC_CHROME, "/opt/google/chrome/chrome"):
        if p and os.path.exists(p):
            return p
    for name in ("google-chrome", "google-chrome-stable", "chrome", "chromium", "chromium-browser"):
        if p := shutil.which(name):
            return p
    return None


def available(headful: bool = False) -> bool:
    """Playwright importable, a Chrome binary present, not disabled with
    FLIGHTSCOUT_BROWSER=0. Everything runs headless: a visible (headful)
    Chrome only when FLIGHTSCOUT_HEADFUL=1 opts in (sources that need one,
    like VivaAerobus and Allegiant, skip otherwise), and then also a display
    (always on macOS and Windows, DISPLAY on Linux)."""
    if os.environ.get("FLIGHTSCOUT_BROWSER") == "0":
        return False
    if headful and os.environ.get("FLIGHTSCOUT_HEADFUL") != "1":
        return False
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    if not chrome_path():
        return False
    if headful and platform.system() == "Linux" and not os.environ.get("DISPLAY"):
        return False
    return True


_procs: dict[subprocess.Popen, str] = {}  # live Chrome processes -> profile dir
_PREFIX = "flightscout-chrome-"


def _kill(proc: subprocess.Popen, profile: str) -> None:
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    except Exception:
        pass
    _procs.pop(proc, None)
    shutil.rmtree(profile, ignore_errors=True)


def _reap_orphans() -> None:
    """Kill Chromes of ours whose Python process died without cleaning up
    (killed with SIGKILL, say): they have been reparented to init."""
    if platform.system() == "Windows":
        return
    try:
        ps = subprocess.run(["ps", "-axo", "pid=,ppid=,command="], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return
    for line in ps.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3 and parts[1] == "1" and "--type=" not in parts[2] \
                and f"--user-data-dir={os.path.join(tempfile.gettempdir(), _PREFIX)}" in parts[2]:
            try:
                os.kill(int(parts[0]), 15)
                prof = parts[2].split("--user-data-dir=")[1].split(" ")[0]
                shutil.rmtree(prof, ignore_errors=True)
            except Exception:
                pass


class _Proc:
    """The shared Chrome process (one headless, one headful), started lazily."""

    def __init__(self, headful: bool):
        self.headful = headful
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        self.port = sock.getsockname()[1]
        sock.close()
        self.profile = tempfile.mkdtemp(prefix=_PREFIX)
        args = [chrome_path(), f"--remote-debugging-port={self.port}", f"--user-data-dir={self.profile}",
                "--no-first-run", "--no-default-browser-check", "--window-size=1440,900",
                "--disable-background-timer-throttling", "--disable-renderer-backgrounding",
                "--disable-backgrounding-occluded-windows", "--lang=en-US"]
        if headful:
            args.append("--window-position=-2400,-2400")
        else:
            args += ["--headless=new", "--screen-info={1440x900}"]
        _reap_orphans()
        self.proc = subprocess.Popen(args + ["about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _procs[self.proc] = self.profile
        self.users = 0  # worker connections (or reservations) on this process

    def alive(self) -> bool:
        return self.proc.poll() is None

    def close(self) -> None:
        _kill(self.proc, self.profile)


class _Conn:
    """One worker thread's Playwright connection to the shared Chrome. Each
    job key (one per airline or site) gets its own page (tab) per connection,
    reused across searches; all pages share the profile's default context, so
    cookies and bot manager tokens carry over."""

    def __init__(self, proc: _Proc):
        from playwright.sync_api import sync_playwright

        self.headful = proc.headful
        self.pw = sync_playwright().start()
        err = None
        for _ in range(100):
            try:
                self.browser = self.pw.chromium.connect_over_cdp(f"http://127.0.0.1:{proc.port}")
                break
            except Exception as e:  # Chrome not listening yet
                err = e
                time.sleep(0.1)
        else:
            self.pw.stop()
            raise RuntimeError(f"could not attach to Chrome: {err}")
        self.pages: OrderedDict[str, Any] = OrderedDict()
        try:
            ctx = self.browser.contexts[0]
            first = ctx.pages[0] if ctx.pages else None
            self.ua = None
            if first:
                self.ua = first.evaluate("navigator.userAgent").replace("HeadlessChrome", "Chrome")
                if self.headful:
                    self._minimize(first)
        except Exception:
            self.pw.stop()  # don't leave the Playwright driver running
            raise

    def _minimize(self, page) -> None:
        try:
            cdp = page.context.new_cdp_session(page)
            wid = cdp.send("Browser.getWindowForTarget")["windowId"]
            cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {"windowState": "minimized"}})
        except Exception as e:
            log.debug("minimize failed: %s", e)

    def page(self, key: str):
        pg = self.pages.get(key)
        if pg is not None and not pg.is_closed():
            self.pages.move_to_end(key)
            return pg
        # a tab per site, but not forever: close the least recently used ones
        while len(self.pages) >= MAX_PAGES:
            _, old = self.pages.popitem(last=False)
            try:
                old.close()
            except Exception:
                pass
        # The profile's default context, not a fresh incognito-like one:
        # Cloudflare Turnstile turns interactive for new contexts (Allegiant).
        # Cookies are per site anyway, so the airlines don't collide.
        ctx = self.browser.contexts[0]
        pg = ctx.new_page()
        if not self.headful and self.ua:
            # headless Chrome says "HeadlessChrome" in the UA and client hints
            ver = self.ua.split("Chrome/")[1].split(" ")[0]
            major = ver.split(".")[0]
            brands = [{"brand": "Google Chrome", "version": major}, {"brand": "Chromium", "version": major},
                      {"brand": "Not=A?Brand", "version": "24"}]
            full = [{"brand": b["brand"], "version": ver if b["version"] == major else "24.0.0.0"} for b in brands]
            plat = {"Darwin": "macOS", "Windows": "Windows"}.get(platform.system(), "Linux")
            meta = {"brands": brands, "fullVersionList": full, "platform": plat, "platformVersion": "",
                    "architecture": "", "model": "", "mobile": False}
            ctx.new_cdp_session(pg).send("Network.setUserAgentOverride", {
                "userAgent": self.ua, "acceptLanguage": "en-US,en", "userAgentMetadata": meta})
        elif self.headful:
            self._minimize(pg)
        self.pages[key] = pg
        return pg

    def close(self) -> None:
        try:
            self.pw.stop()
        except Exception:
            pass


# Several jobs (Google's list, browser airlines, booking sites) run at the
# same time as tabs of the one Chrome process: one worker thread each, since
# Playwright's sync API is bound to its thread. FLIGHTSCOUT_BROWSER_TABS caps it.
TABS = max(1, int(os.environ.get("FLIGHTSCOUT_BROWSER_TABS", 4)))
# Open site tabs kept per worker for reuse (cookies live in the profile, so a
# closed tab costs only a page load next time).
MAX_PAGES = max(2, int(os.environ.get("FLIGHTSCOUT_BROWSER_PAGES", 8)))


class _Pool:
    def __init__(self, headful: bool):
        self.headful = headful
        self.jobs: queue.Queue = queue.Queue()
        self.lock = threading.Lock()
        self.proc: _Proc | None = None
        self.workers: list[_Worker] = []

    def acquire(self) -> _Proc:
        """The live Chrome process, with one user reserved for the caller (in
        the same lock, so an idle worker can't stop it in between)."""
        with self.lock:
            if self.proc is None or not self.proc.alive():
                self.proc = _Proc(self.headful)
            self.proc.users += 1
            return self.proc

    def release(self, proc: _Proc) -> None:
        """A worker dropped its connection: stop that Chrome when nobody uses it."""
        with self.lock:
            proc.users -= 1
            if proc.users <= 0:
                proc.close()
                if self.proc is proc:
                    self.proc = None

    def submit(self, item) -> None:
        with self.lock:
            self.workers = [w for w in self.workers if w.is_alive()]
            if len(self.workers) < TABS and (self.jobs.qsize() >= len(self.workers) - self.busy()):
                w = _Worker(self, len(self.workers))
                self.workers.append(w)
                w.start()
        self.jobs.put(item)

    def busy(self) -> int:
        return sum(1 for w in self.workers if w.busy)


class _Worker(threading.Thread):
    def __init__(self, pool: _Pool, n: int):
        super().__init__(daemon=True, name=f"flightscout-chrome-{'headful' if pool.headful else 'headless'}-{n}")
        self.pool = pool
        self.conn: _Conn | None = None
        self.proc: _Proc | None = None
        self.busy = False

    def _drop(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None
        if self.proc is not None:
            self.pool.release(self.proc)
            self.proc = None

    def run(self) -> None:
        while True:
            try:
                item = self.pool.jobs.get(timeout=IDLE_S)
            except queue.Empty:
                self._drop()  # idle: free the memory, reconnect on the next job
                continue
            if item is None:
                self._drop()
                return
            fn, key, fut = item
            if not fut.set_running_or_notify_cancel():
                continue
            self.busy = True
            try:
                if self.conn is not None and (not self.proc.alive() or not self.conn.browser.is_connected()):
                    self._drop()
                if self.conn is None:
                    self.proc = self.pool.acquire()
                    try:
                        self.conn = _Conn(self.proc)
                    except BaseException:
                        self._drop()
                        raise
                fut.set_result(fn(self.conn.page(key)))
            except BaseException as e:
                fut.set_exception(e)
                if self.conn is not None and not self.conn.browser.is_connected():
                    self._drop()
            finally:
                self.busy = False


_pools: dict[bool, _Pool] = {}
_lock = threading.Lock()


def run(fn: Callable[[Any], Any], key: str, headful: bool = False, timeout: float = 120) -> Any:
    """Run ``fn(page)`` on a browser worker thread with a persistent page for
    ``key`` and return its result. Up to TABS jobs run at the same time."""
    if not available(headful):
        raise RuntimeError("browser sources need Playwright and Google Chrome"
                           + (" and a display" if headful else ""))
    with _lock:
        pool = _pools.get(headful)
        if pool is None:
            pool = _pools[headful] = _Pool(headful)
    fut: Future = Future()
    pool.submit((fn, key, fut))
    return fut.result(timeout=timeout)


def pass_cloudflare(page, timeout: float = 30) -> bool:
    """Wait out a Cloudflare "Just a moment" page. When its Turnstile widget
    turns interactive ("Verify you are human"), click the checkbox once, like
    a person would. Returns True when the page got through."""
    end, clicked = time.time() + timeout, False
    start = time.time()
    while time.time() < end:
        try:
            if "Just a moment" not in (page.title() or ""):
                return True
            if not clicked and time.time() - start > 6:
                for fr in page.frames:
                    if "challenges.cloudflare.com" in fr.url:
                        box = fr.frame_element().bounding_box()
                        if box and box["width"] > 0:
                            page.mouse.click(box["x"] + 28, box["y"] + box["height"] / 2)
                            clicked = True
                            break
        except Exception as e:  # navigation in progress
            log.debug("cloudflare wait: %s", e)
        page.wait_for_timeout(500)
    return False


def capture(page, go: Callable[[], Any], match: Callable[[str], bool], timeout: float = 30,
            settle: float = 0.0, stop: Callable[[], bool] | None = None,
            body: Callable[[str], bool] | None = None) -> list[tuple[str, str]]:
    """Call ``go()`` (usually page.goto) and collect (url, body) of every
    successful response whose URL satisfies ``match``. Returns once at least one arrived
    (plus ``settle`` seconds for siblings), when ``stop()`` turns true (e.g.
    the site redirected to a "no flights" page) or after ``timeout`` seconds.
    ``body`` optionally filters on the response text (GraphQL endpoints)."""
    got: list[tuple[str, str]] = []

    def on(r):
        if match(r.url) and r.request.method != "OPTIONS" and r.ok:
            try:
                txt = r.text()
                if body is None or body(txt):
                    got.append((r.url, txt))
            except Exception as e:
                log.debug("body unavailable for %s: %s", r.url, e)

    page.on("response", on)
    try:
        go()
        end = time.time() + timeout
        while not got and time.time() < end and not (stop and stop()):
            page.wait_for_timeout(200)
        if got and settle:
            page.wait_for_timeout(settle * 1000)
    finally:
        page.remove_listener("response", on)
    return got


def _stop_all() -> None:
    for pool in list(_pools.values()):
        for w in pool.workers:
            if w.is_alive():
                pool.jobs.put(None)
    for pool in list(_pools.values()):
        for w in pool.workers:
            w.join(timeout=5)
    for proc, profile in list(_procs.items()):  # a worker stuck in a job
        _kill(proc, profile)


# Before the interpreter joins non daemon threads (Playwright's asyncio
# executor threads would otherwise block exit while our worker holds them).
getattr(threading, "_register_atexit", atexit.register)(_stop_all)
