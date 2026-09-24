"use client";
// Client side cache of cheapest prices per departure day, from /dates (Google
// calendar merged with Volaris by the engine). Fetched lazily one month at a
// time so the calendar and the nearby dates strip only ask for what's visible.

import { useEffect, useMemo, useSyncExternalStore } from "react";
import { api, ApiError } from "./client";
import { browserGoogleSearch, extensionVersion } from "./extension";
import { localRunnerActive } from "./local-runner";
import { expandCodes } from "./airports-client";
import { isoDate } from "./format";
import type { DatePrice } from "./types";

export type DayPrice = { price: number; currency: string; returnDate?: string | null };
type Entry = { status: "loading" | "ok" | "error"; prices: Map<string, DayPrice>; at: number; error?: string };

const cache = new Map<string, Entry>();
const listeners = new Set<() => void>();
let version = 0;
let cooldownUntil = 0;
let lastError: string | null = null;

function emit() {
  version++;
  listeners.forEach((l) => l());
}

function coolingDown() {
  return Date.now() < cooldownUntil;
}

// With the FlightScout Helper extension, Google's calendar (one page per day,
// our heaviest Google use) is fetched by this browser; the server only adds
// the airline and Skyscanner calendars. Without it, the server does it all.
async function loadDates(o: string, d: string, start: string, end: string, currency: string, tripDays?: number) {
  const body = { origin: o, destination: d, start, end, currency, trip_days: tripDays, quiet: true };
  if (extensionVersion() && !localRunnerActive()) {
    try {
      const [g, rest] = await Promise.all([
        browserGoogleSearch<{ items: DatePrice[] }>(
          { origins: [o], destinations: [d], departure: start, currency, mode: "dates", start, end, trip_days: tripDays },
          (b) => api<{ items: DatePrice[]; need?: string[] }>("/browser", { body: { ...b, quiet: true } }),
        ),
        tripDays ? Promise.resolve({ items: [] as DatePrice[] }) : api<{ items: DatePrice[] }>("/dates", { body: { ...body, skip_google: true } }),
      ]);
      return { items: [...(g.items ?? []), ...(rest.items ?? [])] };
    } catch {
      /* fall back to the server */
    }
  }
  return api<{ items: DatePrice[] }>("/dates", { body });
}

export type PriceQuery = { from: string[]; to: string[]; tripDays: number | null; currency: string };

function routeOf(q: PriceQuery) {
  const o = expandCodes(q.from)[0];
  const d = expandCodes(q.to)[0];
  return o && d && o !== d ? { o, d } : null;
}

function keyFor(q: PriceQuery, month: string) {
  const r = routeOf(q);
  return r ? `${r.o}|${r.d}|${q.tripDays ?? 0}|${q.currency}|${month}` : null;
}

// "2026-10" for any ISO date
export function monthOf(iso: string) {
  return iso.slice(0, 7);
}

export function addMonths(month: string, n: number) {
  const [y, m] = month.split("-").map(Number);
  const d = new Date(Date.UTC(y, m - 1 + n, 1));
  return d.toISOString().slice(0, 7);
}

function monthRange(month: string): [string, string] | null {
  const [y, m] = month.split("-").map(Number);
  const today = isoDate(new Date());
  const first = `${month}-01`;
  const last = new Date(Date.UTC(y, m, 0)).toISOString().slice(0, 10);
  if (last < today) return null;
  return [first < today ? today : first, last];
}

function load(q: PriceQuery, month: string) {
  const key = keyFor(q, month);
  const range = monthRange(month);
  const r = routeOf(q);
  if (!key || !range || !r) return;
  const hit = cache.get(key);
  if (hit && (hit.status !== "error" || Date.now() - hit.at < 120_000)) return;
  if (Date.now() < cooldownUntil) return;
  cache.set(key, { status: "loading", prices: new Map(), at: Date.now() });
  emit();
  loadDates(r.o, r.d, range[0], range[1], q.currency, q.tripDays || undefined)
    .then((res) => {
      const prices = new Map<string, DayPrice>();
      for (const p of res.items ?? []) {
        const cur = prices.get(p.departure);
        if (!cur || p.price < cur.price) prices.set(p.departure, { price: p.price, currency: p.currency, returnDate: p.return_date });
      }
      cache.set(key, { status: "ok", prices, at: Date.now() });
      lastError = null;
    })
    .catch((e: Error) => {
      if (e instanceof ApiError && e.status === 429) cooldownUntil = Date.now() + 5 * 60_000;
      lastError = e.message;
      cache.set(key, { status: "error", prices: new Map(), at: Date.now(), error: e.message });
    })
    .finally(emit);
}

// Prices for the given months (YYYY-MM). Starts fetches for missing months.
export function useDatePrices(q: PriceQuery | null, months: string[]) {
  const v = useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => version,
    () => 0,
  );
  const qKey = q ? `${q.from.join()}|${q.to.join()}|${q.tripDays}|${q.currency}` : "";
  const mKey = months.join();
  useEffect(() => {
    if (!q) return;
    for (const m of months) load(q, m);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [qKey, mKey]);

  return useMemo(() => {
    const prices = new Map<string, DayPrice>();
    const loading = new Set<string>();
    let failed = false;
    let error: string | null = null;
    if (q)
      for (const m of months) {
        const k = keyFor(q, m);
        const e = k ? cache.get(k) : undefined;
        if (!e) {
          if (k && monthRange(m) && !coolingDown()) loading.add(m);
          continue;
        }
        if (e.status === "loading") loading.add(m);
        else if (e.status === "error") {
          failed = true;
          error = e.error ?? lastError;
        } else e.prices.forEach((p, d) => prices.set(d, p));
      }
    return { prices, loading, failed, error, enabled: Boolean(q && routeOf(q)) };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [v, qKey, mKey]);
}

// Price level for coloring: cheap (bottom third) days are green.
export function priceLevels(values: number[]) {
  if (!values.length) return () => "mid" as const;
  const sorted = [...values].sort((a, b) => a - b);
  const lo = sorted[Math.floor(sorted.length * 0.3)];
  const hi = sorted[Math.floor(sorted.length * 0.75)];
  const min = sorted[0];
  return (v: number): "low" | "mid" | "high" => (v <= Math.max(lo, min) ? "low" : v >= hi && hi > lo ? "high" : "mid");
}
