"""Seller and fare breakdown from Google's booking page. Google gated the
internal booking endpoint in August 2026, so this drives a real headless
browser (Playwright) and reads the rendered page. Runs locally or in GitHub
Actions, not on Vercel. Install with `uv tool install '.[browser]'` and
`playwright install chromium`."""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor

from . import cache
from .models import Fare, Offer, Trip

log = logging.getLogger(__name__)

_BOOK = re.compile(r"^Book with (.+?)\s*(Airline)?$")
_PRICE = re.compile(r"^(?:[A-Z]{0,3}\$|€|£|[A-Z]{3}\s?)?\s?([\d.,\s]+)\s?(?:kr|€)?$")
_SKIP = {"Continue", "Hide options", "View options", "Show options", "How options are ranked",
         "Learn more about booking options", ""}


def _price(line: str) -> float | None:
    m = _PRICE.match(line.strip())
    if not m or not re.search(r"\d", m.group(1)):
        return None
    digits = re.sub(r"[^\d]", "", m.group(1))
    return float(digits) if digits else None


def parse(text: str) -> tuple[list[Offer], str | None]:
    i = text.find("Booking options")
    if i < 0:
        return [], None
    j = text.find("Prices include", i)
    k = text.find("Fare and baggage fees", i)
    end = min(x for x in (j, k, len(text)) if x > 0)
    lines = [l.strip() for l in text[i:end].split("\n")]
    offers: list[Offer] = []
    cur: Offer | None = None
    fare_name: str | None = None
    fare: Fare | None = None
    for line in lines[1:]:
        if m := _BOOK.match(line):
            cur = Offer(seller=m.group(1).strip(), is_airline=bool(m.group(2)), fares=[])
            offers.append(cur)
            fare_name, fare = None, None
            continue
        if cur is None or line in _SKIP:
            if line == "Continue":
                fare, fare_name = None, None
            continue
        p = _price(line)
        if p is not None and fare is None:
            fare = Fare(name=fare_name, price=p)
            cur.fares.append(fare)
            continue
        if fare is None:
            fare_name = line  # a fare family name comes before its price
        elif not line.startswith("1st checked bag"):
            fare.features.append(line)
    offers = [o for o in offers if o.fares]
    insight = None
    m = re.search(r"Price insights\n(.+?)\n(.+?)\n", text)
    if m:
        insight = f"{m.group(1)}. {m.group(2)}".strip()
    return offers, insight


def booking_options(url: str, page=None) -> tuple[list[Offer], str | None]:
    key = f"offers:{url}"
    if (hit := cache.get(key, ttl=3 * 3600)) is not None:
        return [Offer(**o) for o in hit["offers"]], hit["insight"]
    own = page is None
    if own:
        from playwright.sync_api import sync_playwright

        pw = sync_playwright().start()
        browser = pw.chromium.launch()
        ctx = browser.new_context(locale="en-US")
        # pre-accepted consent so EU IPs don't land on the consent page
        ctx.add_cookies([{"name": "SOCS", "value": "CAESEwgDEgk0ODE3Nzk3MjQaAmVuIAEaBgiA_LyaBg",
                          "domain": ".google.com", "path": "/"}])
        page = ctx.new_page()
    try:
        sep = "&" if "?" in url else "?"
        page.goto(url + f"{sep}hl=en&gl=US", wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(1200)
        for sel in ("text=/more booking options/i", "text=/^View options$/"):
            try:
                page.click(sel, timeout=800)
                page.wait_for_timeout(600)
            except Exception:
                pass
        offers, insight = parse(page.inner_text("body"))
    finally:
        if own:
            browser.close()
            pw.stop()
    cache.put(key, {"offers": [o.model_dump() for o in offers], "insight": insight})
    return offers, insight


def enrich(trips: list[Trip], top: int = 5, rules: dict[str, str] | None = None) -> None:
    """Attach seller breakdowns to the Google tickets of the first ``top``
    trips. Sellers on the block list are removed, warned ones get flagged, and
    the ticket price becomes the cheapest allowed seller."""
    from playwright.sync_api import sync_playwright

    from .sellers import DEFAULT_RULES

    lower = {k.lower(): v for k, v in {**DEFAULT_RULES, **(rules or {})}.items()}
    picked = [t for t in trips if any(tk.source == "google" for tk in t.tickets)][:top]
    tickets = [tk for t in picked for tk in t.tickets if tk.source == "google"]
    if not tickets:
        return
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(locale="en-US")
        ctx.add_cookies([{"name": "SOCS", "value": "CAESEwgDEgk0ODE3Nzk3MjQaAmVuIAEaBgiA_LyaBg",
                          "domain": ".google.com", "path": "/"}])
        page = ctx.new_page()
        for tk in tickets:
            try:
                offers, insight = booking_options(tk.booking_url, page)
            except Exception as e:
                log.warning("booking options failed: %s", e)
                continue
            offers = [o for o in offers if lower.get(o.seller.lower()) != "block"]
            tk.offers = offers
            tk.price_insight = insight
            if offers:
                cheapest = None
                best = min(offers, key=lambda o: o.cheapest)
                tk.seller = best.seller
                tk.seller_kind = "airline" if best.is_airline else "ota"
                if not any(o.is_airline for o in offers):
                    tk.warnings.append("Only sold by travel agencies, not by the airline directly.")
                cheapest = min((f for o in offers for f in o.fares), key=lambda f: f.price)
                feats = " ".join(cheapest.features).lower()
                if "carry-on" in feats and ("fee" in feats or "no carry-on" in feats) and "free carry-on" not in feats:
                    tk.warnings.append(f"Cheapest fare ({cheapest.name or 'basic'}) has no free carry-on bag.")
                if "no seat selection" in feats or "no ticket changes" in feats:
                    tk.warnings.append(f"Cheapest fare ({cheapest.name or 'basic'}) is basic: no changes or seat choice.")
                for o in offers:
                    if lower.get(o.seller.lower()) == "warn":
                        tk.warnings.append(f"{o.seller} is on your seller warning list.")
        browser.close()
    for t in picked:
        t.risks = list(dict.fromkeys(t.risks + [w for tk in t.tickets for w in tk.warnings]))
