"use client";
// Guest mode: the same /api/v1 routes the server offers for signed in users,
// answered from localStorage. The client `api()` helper routes here when the
// visitor has no session, so pages don't need to know which mode they're in.
// Engine calls (search, plan, explore, dates, trip) still go to the server.

import { DEFAULT_PLANNER } from "./defaults";
import type { PlannerDefaults, SellerRule } from "./db/schema";
import type { PlanResult, SearchQuery, SearchResult, Trip } from "./types";
import { alertReasons, queryMatchesWatch, tripsToObservations, watchToQuery, type ObservationInput } from "./watch-logic";

const P = "fs.guest.";
const MAX_OBS_PER_WATCH = 3000;
const MAX_SEARCHES = 40;
const SEARCHES_WITH_PAYLOAD = 8;

export class GuestError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

// ---------------------------------------------------------------------------
// storage helpers (every access is wrapped: private mode, quota, blocked)
// ---------------------------------------------------------------------------

function read<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(P + key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function write(key: string, value: unknown) {
  try {
    localStorage.setItem(P + key, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}

function remove(key: string) {
  try {
    localStorage.removeItem(P + key);
  } catch {}
}

function nextId() {
  const n = read<number>("seq", 0) + 1;
  write("seq", n);
  return n;
}

// ---------------------------------------------------------------------------
// shapes (mirror the server's JSON)
// ---------------------------------------------------------------------------

export type GuestSettings = {
  userId: "guest";
  currency: string;
  defaultOrigins: string[];
  planner: PlannerDefaults;
  sellerRules: SellerRule[];
  emailAlerts: false;
  pushAlerts: false;
  onboarded: boolean;
};

type Place = { id: number; label: string; codes: string[]; kind: "home" | "frequent" | "interested"; color?: string | null; notes?: string | null; createdAt: string };

type Watch = {
  id: number;
  userId: "guest";
  name: string;
  origins: string[];
  destinations: string[];
  tripType: "oneway" | "roundtrip";
  departStart: string;
  departEnd: string;
  nightsMin: number | null;
  nightsMax: number | null;
  cabin: string;
  adults: number;
  maxStops: number | null;
  currency: string;
  includeSplit: boolean;
  alertBelow: number | null;
  alertDropPct: number | null;
  active: boolean;
  lastCheckedAt: string | null;
  bestPrice: number | null;
  prevPrice: number | null;
  lowestPrice: number | null;
  bestTrip: unknown;
  notes: string | null;
  createdAt: string;
};

type Obs = {
  id: number;
  observed_at: string;
  depart_date: string;
  return_date: string | null;
  price: number;
  currency: string;
  source: string;
  kind: string;
  route: string | null;
  duration_min: number | null;
  booking_url: string | null;
};

type SearchRow = {
  id: number;
  kind: "search" | "plan" | "explore" | "dates" | "trip" | "multicity";
  origin: "web";
  summary: string;
  query: Record<string, unknown>;
  payload: unknown;
  createdAt: string;
};

type Alert = { id: number; watchId: number; message: string; price: number; currency: string; bookingUrl: string | null; createdAt: string; readAt: string | null };

export function guestSettings(): GuestSettings {
  const s = read<Partial<GuestSettings>>("settings", {});
  return {
    userId: "guest",
    currency: s.currency ?? "USD",
    defaultOrigins: s.defaultOrigins ?? [],
    planner: { ...DEFAULT_PLANNER, ...(s.planner ?? {}) },
    sellerRules: s.sellerRules ?? [],
    emailAlerts: false,
    pushAlerts: false,
    onboarded: s.onboarded ?? false,
  };
}

export function hasGuestData() {
  const s = read<Partial<GuestSettings>>("settings", {});
  return (
    read<Place[]>("places", []).length > 0 ||
    read<Watch[]>("watches", []).length > 0 ||
    read<SearchRow[]>("searches", []).length > 0 ||
    Boolean(s.sellerRules?.length || s.currency || s.planner)
  );
}

export function guestSnapshot() {
  const watches = read<Watch[]>("watches", []);
  return {
    settings: guestSettings(),
    places: read<Place[]>("places", []),
    watches: watches.map((w) => ({ watch: w, observations: read<Obs[]>(`obs.${w.id}`, []) })),
    searches: read<SearchRow[]>("searches", []),
  };
}

export function clearGuestData() {
  try {
    const keys: string[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k?.startsWith(P)) keys.push(k);
    }
    keys.forEach((k) => localStorage.removeItem(k));
  } catch {}
}

// ---------------------------------------------------------------------------
// fx (for comparing prices across currencies in watches)
// ---------------------------------------------------------------------------

let rates: Record<string, number> | null = null;
async function getRates(serverFetch: ServerFetch) {
  if (rates) return rates;
  try {
    rates = (await serverFetch<{ rates: Record<string, number> }>("/fx")).rates;
  } catch {
    rates = { EUR: 1 };
  }
  return rates;
}
function conv(r: Record<string, number>, amount: number, from: string, to: string) {
  if (from === to || !r[from] || !r[to]) return amount;
  return (amount / r[from]) * r[to];
}

// ---------------------------------------------------------------------------
// watches
// ---------------------------------------------------------------------------

const codes = (v: unknown) =>
  (Array.isArray(v) ? v : String(v ?? "").split(","))
    .map((c) => String(c).trim().toUpperCase())
    .filter((c) => /^[A-Z]{3,4}$/.test(c));

function watchFromInput(p: Record<string, unknown>, base?: Watch): Watch {
  const pick = <T,>(k: string, cur: T): T => (k in p ? (p[k] as T) : cur);
  const origins = "origins" in p ? codes(p.origins) : (base?.origins ?? []);
  const destinations = "destinations" in p ? codes(p.destinations) : (base?.destinations ?? []);
  if (!origins.length || !destinations.length) throw new GuestError(400, "origins and destinations are required");
  const departStart = pick<string>("depart_start", base?.departStart ?? "");
  if (!/^\d{4}-\d{2}-\d{2}$/.test(departStart)) throw new GuestError(400, "depart_start must be YYYY-MM-DD");
  const departEnd = pick<string>("depart_end", base?.departEnd ?? departStart) || departStart;
  if (departEnd < departStart) throw new GuestError(400, "depart_end is before depart_start");
  return {
    id: base?.id ?? nextId(),
    userId: "guest",
    name: String(pick("name", base?.name ?? "") || `${origins.join("/")} to ${destinations.join("/")}`).slice(0, 120),
    origins,
    destinations,
    tripType: pick("trip_type", base?.tripType ?? "roundtrip") === "oneway" ? "oneway" : "roundtrip",
    departStart,
    departEnd,
    nightsMin: pick("nights_min", base?.nightsMin ?? null),
    nightsMax: pick("nights_max", base?.nightsMax ?? null),
    cabin: pick("cabin", base?.cabin ?? "economy"),
    adults: Math.max(1, Math.min(9, Number(pick("adults", base?.adults ?? 1)))),
    maxStops: pick("max_stops", base?.maxStops ?? null),
    currency: pick("currency", base?.currency ?? guestSettings().currency),
    includeSplit: Boolean(pick("include_split", base?.includeSplit ?? false)),
    alertBelow: pick("alert_below", base?.alertBelow ?? null),
    alertDropPct: pick("alert_drop_pct", base?.alertDropPct ?? null),
    active: Boolean(pick("active", base?.active ?? true)),
    lastCheckedAt: base?.lastCheckedAt ?? null,
    bestPrice: base?.bestPrice ?? null,
    prevPrice: base?.prevPrice ?? null,
    lowestPrice: base?.lowestPrice ?? null,
    bestTrip: base?.bestTrip ?? null,
    notes: pick("notes", base?.notes ?? null),
    createdAt: base?.createdAt ?? new Date().toISOString(),
  };
}

function getWatch(id: number) {
  const w = read<Watch[]>("watches", []).find((x) => x.id === id);
  if (!w) throw new GuestError(404, "watch not found");
  return w;
}

function saveWatch(w: Watch) {
  const list = read<Watch[]>("watches", []);
  const i = list.findIndex((x) => x.id === w.id);
  if (i >= 0) list[i] = w;
  else list.unshift(w);
  write("watches", list);
}

async function recordObservations(w: Watch, obs: ObservationInput[], serverFetch: ServerFetch) {
  if (!obs.length) {
    saveWatch({ ...w, lastCheckedAt: new Date().toISOString() });
    return { inserted: 0, alerts: 0 };
  }
  const r = await getRates(serverFetch);
  const now = new Date().toISOString();
  const existing = read<Obs[]>(`obs.${w.id}`, []);
  let seq = existing.at(-1)?.id ?? 0;
  const rows: Obs[] = obs.map((o) => ({
    id: ++seq,
    observed_at: o.observed_at ?? now,
    depart_date: o.depart_date,
    return_date: o.return_date ?? null,
    price: o.price,
    currency: o.currency,
    source: o.source,
    kind: o.kind ?? "single",
    route: o.route ?? null,
    duration_min: o.duration_min ?? null,
    booking_url: o.booking_url ?? null,
  }));
  let all = [...existing, ...rows];
  if (all.length > MAX_OBS_PER_WATCH) all = all.slice(-MAX_OBS_PER_WATCH);
  // On quota errors drop the oldest half and try again.
  while (!write(`obs.${w.id}`, all) && all.length > 50) all = all.slice(Math.floor(all.length / 2));

  let best = obs[0];
  let bestVal = Infinity;
  for (const o of obs) {
    const v = conv(r, o.price, o.currency, w.currency);
    if (v < bestVal) {
      bestVal = v;
      best = o;
    }
  }
  const prev = w.bestPrice;
  saveWatch({
    ...w,
    prevPrice: prev,
    bestPrice: bestVal,
    lowestPrice: w.lowestPrice == null ? bestVal : Math.min(w.lowestPrice, bestVal),
    bestTrip: best.trip ?? w.bestTrip,
    lastCheckedAt: now,
  });
  const reasons = alertReasons(w, bestVal, prev);
  if (reasons.length) {
    const alerts = read<Alert[]>("alerts", []);
    alerts.unshift({
      id: nextId(),
      watchId: w.id,
      message: `${w.name} ${reasons.join(" and ")}`,
      price: bestVal,
      currency: w.currency,
      bookingUrl: best.booking_url ?? null,
      createdAt: now,
      readAt: null,
    });
    write("alerts", alerts.slice(0, 50));
  }
  return { inserted: rows.length, alerts: reasons.length ? 1 : 0 };
}

async function checkWatch(w: Watch, serverFetch: ServerFetch) {
  const s = guestSettings();
  const q = watchToQuery(w);
  const res = await serverFetch<SearchResult>("/search", { body: { ...q, sellerRules: s.sellerRules } });
  let trips: Trip[] = res.trips;
  const errors: Record<string, string> = { ...res.errors };
  if (w.includeSplit) {
    try {
      const plan = await serverFetch<PlanResult>("/plan", {
        body: {
          origins: w.origins,
          destinations: w.destinations,
          depart_start: w.departStart,
          depart_end: w.departEnd,
          currency: w.currency,
          cabin: w.cabin,
          adults: w.adults,
          sellerRules: s.sellerRules,
          ...s.planner,
        },
      });
      trips = [...trips, ...plan.trips.filter((t) => t.tickets.length > 1)];
      Object.assign(errors, plan.errors);
    } catch (e) {
      errors.plan = (e as Error).message;
    }
  }
  const out = await recordObservations(w, tripsToObservations(trips, w.destinations), serverFetch);
  saveSearch("search", q as unknown as Record<string, unknown>, { ...res, trips, errors }, `Watch check: ${w.name}`);
  return { ...out, trips: trips.length, errors };
}

// ---------------------------------------------------------------------------
// history
// ---------------------------------------------------------------------------

function summarize(kind: SearchRow["kind"], q: Record<string, unknown>) {
  const list = (v: unknown) => (Array.isArray(v) ? v.join("/") : typeof v === "string" ? v : "?");
  if (kind === "explore") return `Explore from ${list(q.origin)} ${q.start ?? ""} to ${q.end ?? ""}`.trim();
  if (kind === "dates") return `Date prices ${list(q.origin)} to ${list(q.destination)}`;
  if (kind === "trip") {
    const stops = Array.isArray(q.stops) ? (q.stops as { place: string }[]).map((s) => s.place).join(", ") : "";
    return `Trip from ${list(q.start)} via ${stops}`;
  }
  const dep = (q.departure ?? q.depart_start) as string | undefined;
  const ret = (q.return_date ?? q.return_start) as string | undefined;
  return `${kind === "plan" ? "Smart routes " : ""}${list(q.origins)} to ${list(q.destinations)}${dep ? ` ${dep}` : ""}${ret ? ` to ${ret}` : ""}`;
}

export function saveSearch(kind: SearchRow["kind"], query: Record<string, unknown>, payload: unknown, summary?: string) {
  const list = read<SearchRow[]>("searches", []);
  const row: SearchRow = {
    id: nextId(),
    kind,
    origin: "web",
    summary: summary ?? summarize(kind, query),
    query,
    payload,
    createdAt: new Date().toISOString(),
  };
  let next = [row, ...list].slice(0, MAX_SEARCHES).map((r, i) => (i < SEARCHES_WITH_PAYLOAD ? r : { ...r, payload: null }));
  while (!write("searches", next) && next.some((r) => r.payload)) {
    // trim payloads from the oldest until it fits
    const idx = next.map((r) => Boolean(r.payload)).lastIndexOf(true);
    next = next.map((r, i) => (i === idx ? { ...r, payload: null } : r));
  }
  return row.id;
}

// After a guest search, feed any matching local watches (like the server does).
export async function afterGuestEngineCall(kind: string, query: Record<string, unknown>, result: Record<string, unknown>, serverFetch: ServerFetch) {
  if (!["search", "plan", "explore", "dates", "trip", "multicity"].includes(kind)) return;
  saveSearch(kind as SearchRow["kind"], query, result);
  const trips = result.trips as Trip[] | undefined;
  if ((kind !== "search" && kind !== "plan") || !trips?.length) return;
  const q: SearchQuery =
    kind === "search"
      ? (query as unknown as SearchQuery)
      : {
          origins: query.origins as string[],
          destinations: query.destinations as string[],
          departure: query.depart_start as string,
          return_date: (query.return_start as string) ?? null,
          cabin: (query.cabin as SearchQuery["cabin"]) ?? "economy",
        };
  for (const w of read<Watch[]>("watches", [])) {
    if (queryMatchesWatch(q, w)) await recordObservations(w, tripsToObservations(trips, w.destinations), serverFetch);
  }
}

// ---------------------------------------------------------------------------
// router
// ---------------------------------------------------------------------------

export type ServerFetch = <T>(path: string, init?: { method?: string; body?: unknown }) => Promise<T>;

const ENGINE = new Set(["/search", "/plan", "/explore", "/dates", "/trip", "/fx", "/me", "/results", "/multicity"]);

export function isGuestRoute(path: string) {
  const p = path.split("?")[0];
  return !ENGINE.has(p);
}

export async function guestApi(path: string, method: string, body: unknown, serverFetch: ServerFetch): Promise<unknown> {
  const [p, qs] = path.split("?");
  const params = new URLSearchParams(qs ?? "");
  const seg = p.split("/").filter(Boolean);
  const b = (body ?? {}) as Record<string, unknown>;

  switch (seg[0]) {
    case "settings": {
      if (method !== "PATCH") break;
      const cur = guestSettings();
      const next = {
        currency: (b.currency as string) ?? cur.currency,
        defaultOrigins: b.defaultOrigins ? codes(b.defaultOrigins) : cur.defaultOrigins,
        planner: b.planner ? { ...cur.planner, ...(b.planner as object) } : cur.planner,
        sellerRules: (b.sellerRules as SellerRule[]) ?? cur.sellerRules,
        onboarded: (b.onboarded as boolean) ?? cur.onboarded,
      };
      write("settings", next);
      return guestSettings();
    }
    case "places": {
      const list = read<Place[]>("places", []);
      if (!seg[1]) {
        if (method === "GET") return [...list].sort((a, b) => a.kind.localeCompare(b.kind) || a.label.localeCompare(b.label));
        const c = codes(b.codes);
        if (!String(b.label ?? "").trim() || !c.length) throw new GuestError(400, "label and at least one airport code are required");
        const row: Place = { id: nextId(), label: String(b.label).trim(), codes: c, kind: (b.kind as Place["kind"]) ?? "frequent", color: null, notes: null, createdAt: new Date().toISOString() };
        write("places", [...list, row]);
        return row;
      }
      const id = Number(seg[1]);
      if (method === "DELETE") {
        write("places", list.filter((x) => x.id !== id));
        return { ok: true };
      }
      if (method === "PATCH") {
        const next = list.map((x) => (x.id === id ? { ...x, ...b, codes: b.codes ? codes(b.codes) : x.codes } : x));
        write("places", next);
        return next.find((x) => x.id === id);
      }
      break;
    }
    case "watches": {
      if (!seg[1]) {
        if (method === "GET") {
          const r = await getRates(serverFetch);
          return read<Watch[]>("watches", []).map((w) => {
            const days = new Map<string, number>();
            for (const o of read<Obs[]>(`obs.${w.id}`, [])) {
              const d = o.observed_at.slice(0, 10);
              const v = conv(r, o.price, o.currency, w.currency);
              days.set(d, Math.min(days.get(d) ?? Infinity, v));
            }
            return { ...w, sparkline: [...days.entries()].sort().slice(-90).map(([day, price]) => ({ day, price: Math.round(price) })) };
          });
        }
        const w = watchFromInput(b);
        saveWatch(w);
        return w;
      }
      const id = Number(seg[1]);
      const w = getWatch(id);
      if (!seg[2]) {
        if (method === "GET") return w;
        if (method === "PATCH") {
          const next = watchFromInput(b, w);
          saveWatch(next);
          return next;
        }
        if (method === "DELETE") {
          write("watches", read<Watch[]>("watches", []).filter((x) => x.id !== id));
          remove(`obs.${id}`);
          return { ok: true };
        }
      }
      if (seg[2] === "history") {
        const r = await getRates(serverFetch);
        const days = Number(params.get("days") ?? 365);
        const since = new Date(Date.now() - days * 86400_000).toISOString();
        return {
          watch: w,
          observations: read<Obs[]>(`obs.${id}`, [])
            .filter((o) => o.observed_at >= since)
            .map((o) => ({ ...o, has_trip: false, value: Math.round(conv(r, o.price, o.currency, w.currency) * 100) / 100 })),
        };
      }
      if (seg[2] === "check") return checkWatch(w, serverFetch);
      if (seg[2] === "observations") {
        const list = Array.isArray(body) ? (body as ObservationInput[]) : (b.observations as ObservationInput[]);
        return recordObservations(w, list ?? [], serverFetch);
      }
      break;
    }
    case "searches": {
      const list = read<SearchRow[]>("searches", []);
      if (!seg[1]) {
        const limit = Number(params.get("limit") ?? 50);
        const before = params.get("before");
        return list
          .filter((r) => !before || r.id < Number(before))
          .slice(0, limit)
          .map((r) => ({ id: r.id, kind: r.kind, origin: r.origin, summary: r.summary, query: r.query, created_at: r.createdAt }));
      }
      const id = Number(seg[1]);
      if (method === "DELETE") {
        write("searches", list.filter((r) => r.id !== id));
        return { ok: true };
      }
      const row = list.find((r) => r.id === id);
      if (!row) throw new GuestError(404, "not found");
      return row;
    }
    case "alerts": {
      const list = read<Alert[]>("alerts", []);
      if (method === "GET") return { alerts: list, unread: list.filter((a) => !a.readAt).length };
      const now = new Date().toISOString();
      const ids = new Set((b.ids as number[]) ?? []);
      write("alerts", list.map((a) => (b.all || ids.has(a.id) ? { ...a, readAt: a.readAt ?? now } : a)));
      return { ok: true };
    }
    case "tokens":
      if (method === "GET") return [];
      throw new GuestError(403, "Sign in to create API tokens for the CLI and agents.");
    case "push":
      throw new GuestError(403, "Sign in to get push alerts.");
  }
  throw new GuestError(404, `not available in guest mode: ${method} ${path}`);
}

