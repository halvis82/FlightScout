"use client";
import { placeSignature, watchSignature } from "./signature";
import { HttpError } from "./http-error";
import { placeInput } from "./place-validate";
import { addDays } from "./format";
import { cleanCurrency, cleanOrigins, cleanPlanner, cleanSellerRules } from "./settings-validate";
import { checkWatch as checkWatchFields, isDate, toColumns, type WatchIn } from "./watch-validate";
// Guest mode: the same /api/v1 routes the server offers for signed in users,
// answered from localStorage. The client `api()` helper routes here when the
// visitor has no session, so pages don't need to know which mode they're in.
// Engine calls (search, plan, explore, dates, trip) still go to the server.

import { DEFAULT_PLANNER } from "./defaults";
import type { PlannerDefaults, SellerRule } from "./db/schema";
import type { PlanResult, SearchQuery, SearchResult, Trip } from "./types";
import { alertReasons, queryMatchesWatch, tripsForWatch, tripsToObservations, watchToQuery, type ObservationInput } from "./watch-logic";

const P = "fs.guest.";
const MAX_OBS_PER_WATCH = 3000;
const MAX_SEARCHES = 40;
const SEARCHES_WITH_PAYLOAD = 8;

// Shared validation throws HttpError: the guest router answers with the same status.
function checked<T>(fn: () => T): T {
  try {
    return fn();
  } catch (e) {
    if (e instanceof HttpError) throw new GuestError(e.status, e.message);
    throw e;
  }
}

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
  tripType: "oneway" | "roundtrip" | "multicity";
  legs?: unknown;
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
  pricesSince?: string | null; // like the server: earlier prices describe another search
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
    currency: typeof s.currency === "string" ? s.currency : "USD",
    defaultOrigins: Array.isArray(s.defaultOrigins) ? s.defaultOrigins : [],
    planner: (() => {
      try {
        return cleanPlanner(s.planner ?? {});
      } catch {
        return DEFAULT_PLANNER;
      }
    })(),
    sellerRules: cleanSellerRules(s.sellerRules ?? [], false),
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

// Did the guest change any setting from the defaults (or from the account's
// currency)? Only then is there anything to bring along.
export function guestSettingsChanged(accountCurrency: string) {
  const s = read<Partial<GuestSettings>>("settings", {});
  const planner = s.planner && JSON.stringify({ ...DEFAULT_PLANNER, ...s.planner }) !== JSON.stringify(DEFAULT_PLANNER);
  return Boolean(s.sellerRules?.length || s.defaultOrigins?.length || planner || (s.currency && s.currency !== accountCurrency));
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
    const got = (await serverFetch<{ rates: Record<string, number> }>("/fx")).rates;
    if (got && typeof got.USD === "number") rates = got;
    return got ?? { EUR: 1 };
  } catch {
    return { EUR: 1 }; // not remembered: the next call tries again
  }
}
function conv(r: Record<string, number>, amount: number, from: string, to: string) {
  if (from === to || !r[from] || !r[to]) return amount;
  return (amount / r[from]) * r[to];
}

// ---------------------------------------------------------------------------
// watches
// ---------------------------------------------------------------------------

function watchFromInput(p: Record<string, unknown>, base?: Watch): Watch {
  const c = checked(() => toColumns(p as WatchIn, Boolean(base))) as Partial<Watch>;
  const next: Watch = {
    id: base?.id ?? nextId(),
    userId: "guest",
    name: "",
    origins: [],
    destinations: [],
    tripType: "roundtrip",
    legs: undefined,
    departStart: "",
    departEnd: "",
    nightsMin: null,
    nightsMax: null,
    cabin: "economy",
    adults: 1,
    maxStops: null,
    currency: guestSettings().currency,
    includeSplit: false,
    alertBelow: null,
    alertDropPct: null,
    active: true,
    lastCheckedAt: null,
    bestPrice: null,
    prevPrice: null,
    lowestPrice: null,
    bestTrip: null,
    pricesSince: null,
    notes: null,
    createdAt: new Date().toISOString(),
    ...base,
    ...Object.fromEntries(Object.entries(c).filter(([, v]) => v !== undefined)),
  };
  next.name ||= `${next.origins.join("/")} to ${next.destinations.join("/")}`;
  // a one way watch has no trip length (also when edited from round trip)
  if (next.tripType === "oneway") next.nightsMin = next.nightsMax = null;
  checked(() => checkWatchFields(next));
  if (base) {
    const sig = (w: Watch) => watchSignature(w);
    if (sig(next) !== sig(base) || next.currency !== base.currency) {
      // another search now: earlier prices no longer describe it
      Object.assign(next, { pricesSince: new Date().toISOString(), bestPrice: null, prevPrice: null, lowestPrice: null, bestTrip: null });
      if (next.currency !== base.currency && !("alert_below" in p) && base.alertBelow != null && rates)
        next.alertBelow = Math.round(conv(rates, base.alertBelow, base.currency, next.currency));
    }
  }
  return next;
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
  const r = await getRates(serverFetch);
  const now = new Date().toISOString();
  const today = now.slice(0, 10);
  // only real, future prices in a currency we can compare (like the server)
  const good = obs.filter(
    (o) => o && typeof o.price === "number" && Number.isFinite(o.price) && o.price > 0 && isDate(o.depart_date) && o.depart_date >= today && Boolean(r[String(o.currency).toUpperCase()]),
  );
  if (!good.length) {
    saveWatch({ ...w, lastCheckedAt: now });
    return { inserted: 0, alerts: 0 };
  }
  const existing = read<Obs[]>(`obs.${w.id}`, []);
  let seq = existing.at(-1)?.id ?? 0;
  const clamp = (t?: string | null) => {
    const ms = t ? Date.parse(t) : NaN;
    return Number.isFinite(ms) ? new Date(Math.min(Date.now(), Math.max(Date.now() - 7 * 86400_000, ms))).toISOString() : now;
  };
  const rows: Obs[] = good.map((o) => ({
    id: ++seq,
    observed_at: clamp(o.observed_at),
    depart_date: o.depart_date,
    return_date: isDate(o.return_date) ? o.return_date : null,
    price: o.price,
    currency: o.currency.toUpperCase(),
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

  // The current best is the cheapest fresh price (the last day, dates still
  // ahead), not just this batch, so a narrow search can't fake a "drop" later.
  const since = Math.max(Date.now() - 24 * 3600_000, w.pricesSince ? Date.parse(w.pricesSince) : 0);
  let best: Obs | null = null;
  let bestVal = Infinity;
  for (const o of all) {
    if (Date.parse(o.observed_at) < since || o.depart_date < today) continue;
    const v = conv(r, o.price, o.currency, w.currency);
    if (v < bestVal) {
      bestVal = v;
      best = o;
    }
  }
  if (!best) return { inserted: rows.length, alerts: 0 };
  bestVal = Math.round(bestVal * 100) / 100;
  const inBatch = rows.findIndex((x) => x.id === best!.id);
  const prev = w.bestPrice;
  saveWatch({
    ...w,
    prevPrice: prev,
    bestPrice: bestVal,
    lowestPrice: w.lowestPrice == null ? bestVal : Math.min(w.lowestPrice, bestVal),
    bestTrip: inBatch >= 0 ? (good[inBatch].trip ?? w.bestTrip) : w.bestTrip,
    lastCheckedAt: now,
  });
  const reasons = alertReasons(w, bestVal, prev);
  // like the server: not the same alert again within 12 hours unless the price fell further
  const recent = read<Alert[]>("alerts", []).find((a) => a.watchId === w.id && Date.now() - Date.parse(a.createdAt) < 12 * 3600_000);
  const fire = reasons.length > 0 && !(recent && recent.price <= bestVal);
  if (fire) addAlert(w, reasons, bestVal, best.booking_url ?? null);
  return { inserted: rows.length, alerts: fire ? 1 : 0 };
}

function addAlert(w: Watch, reasons: string[], price: number, bookingUrl: string | null) {
  const alerts = read<Alert[]>("alerts", []);
  alerts.unshift({
    id: nextId(),
    watchId: w.id,
    message: `${w.name} ${reasons.join(" and ")}`,
    price,
    currency: w.currency,
    bookingUrl,
    createdAt: new Date().toISOString(),
    readAt: null,
  });
  write("alerts", alerts.slice(0, 50));
}

async function checkWatch(w: Watch, serverFetch: ServerFetch) {
  const s = guestSettings();
  if (w.tripType === "multicity" && Array.isArray(w.legs) && w.legs.length) {
    // the whole multi city trip, like the server's tracker does
    const plan = await serverFetch<PlanResult>("/multicity", { body: { legs: w.legs, currency: w.currency, cabin: w.cabin, adults: w.adults } });
    const out = await recordObservations(w, tripsToObservations(plan.trips.slice(0, 5), w.destinations), serverFetch);
    return { ...out, trips: plan.trips.length, errors: plan.errors ?? {} };
  }
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
          // round trips come back after the watch's stay, like the server's check
          return_start: q.return_date ? addDays(w.departStart, w.nightsMin ?? 7) : null,
          return_end: q.return_date ? addDays(w.departEnd, w.nightsMax ?? w.nightsMin ?? 7) : null,
          currency: w.currency,
          cabin: w.cabin,
          adults: w.adults,
          sellerRules: s.sellerRules,
          max_stopover_days: Math.min(s.planner.max_stopover_days, 3),
          min_connection_hours: s.planner.min_connection_hours,
          max_trip_days: s.planner.max_trip_days,
          max_hubs: Math.min(s.planner.max_hubs, 6),
          allow_self_transfer: s.planner.allow_self_transfer,
          include_nested_roundtrips: s.planner.include_nested_roundtrips,
        },
      });
      trips = [...trips, ...plan.trips.filter((t) => t.tickets.length > 1)];
      Object.assign(errors, plan.errors);
    } catch (e) {
      errors.plan = (e as Error).message;
    }
  }
  const out = await recordObservations(w, tripsToObservations(w.tripType === "multicity" ? trips : tripsForWatch(trips, w), w.destinations), serverFetch);
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
  let list = read<SearchRow[]>("searches", []);
  // the same search again soon (a reload, back and forth) replaces its row
  const same = JSON.stringify(query);
  list = list.filter((r) => !(r.kind === kind && Date.now() - Date.parse(r.createdAt) < 30 * 60_000 && JSON.stringify(r.query) === same));
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
  if (!["search", "plan", "explore", "dates", "trip", "multicity"].includes(kind)) return null;
  const id = saveSearch(kind as SearchRow["kind"], query, result);
  await feedGuestWatches(kind, query, result.trips as Trip[] | undefined, serverFetch);
  return id;
}

async function feedGuestWatches(kind: string, query: Record<string, unknown>, trips: Trip[] | undefined, serverFetch: ServerFetch) {
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
    if (!queryMatchesWatch(q, w)) continue;
    const mine = tripsForWatch(trips, w);
    if (mine.length) await recordObservations(w, tripsToObservations(mine, w.destinations), serverFetch);
  }
}

// ---------------------------------------------------------------------------
// router
// ---------------------------------------------------------------------------

export type ServerFetch = <T>(path: string, init?: { method?: string; body?: unknown }) => Promise<T>;

const ENGINE = new Set(["/search", "/plan", "/explore", "/dates", "/trip", "/fx", "/me", "/results", "/multicity", "/explore/cached", "/browser"]);

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
      const next = checked(() => ({
        currency: b.currency !== undefined ? cleanCurrency(b.currency) : cur.currency,
        defaultOrigins: b.defaultOrigins !== undefined ? cleanOrigins(b.defaultOrigins) : cur.defaultOrigins,
        planner: b.planner !== undefined ? cleanPlanner(b.planner, cur.planner) : cur.planner,
        sellerRules: b.sellerRules !== undefined ? cleanSellerRules(b.sellerRules) : cur.sellerRules,
        onboarded: b.onboarded !== undefined ? Boolean(b.onboarded) : cur.onboarded,
      }));
      write("settings", next);
      return guestSettings();
    }
    case "places": {
      const list = read<Place[]>("places", []);
      if (!seg[1]) {
        if (method === "GET") return [...list].sort((a, b) => a.kind.localeCompare(b.kind) || a.label.localeCompare(b.label));
        const v = checked(() => placeInput(b, false));
        const c = v.codes!;
        const dupPlace = list.find((x) => placeSignature(x.codes) === placeSignature(c));
        if (dupPlace) return { ...dupPlace, existing: true };
        const row: Place = { id: nextId(), label: v.label!, codes: c, kind: v.kind!, color: v.color ?? null, notes: v.notes ?? null, createdAt: new Date().toISOString() };
        write("places", [...list, row]);
        return row;
      }
      const id = Number(seg[1]);
      // "Start searches from" holds a copy of a favorite's codes: keep it in step
      const syncDefault = (old: string[], now: string[]) => {
        const st = guestSettings();
        if (st.defaultOrigins.length && placeSignature(st.defaultOrigins) === placeSignature(old)) write("settings", { ...st, defaultOrigins: now });
      };
      const prev = list.find((x) => x.id === id);
      if (method === "DELETE") {
        write("places", list.filter((x) => x.id !== id));
        if (prev) syncDefault(prev.codes, []);
        return { ok: true };
      }
      if (method === "PATCH") {
        const v = checked(() => placeInput(b, true));
        delete v.signature;
        if (v.codes && list.some((x) => x.id !== id && placeSignature(x.codes) === placeSignature(v.codes!)))
          throw new GuestError(409, "You already saved a place with exactly these airports.");
        const next = list.map((x) => (x.id === id ? { ...x, ...v } : x));
        write("places", next);
        const row = next.find((x) => x.id === id);
        if (prev && row && b.codes) syncDefault(prev.codes, row.codes);
        return row;
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
        // the same search saved twice returns the existing watch
        const sig = watchSignature(w as never);
        const dup = read<Watch[]>("watches", []).find((x) => watchSignature(x as never) === sig);
        if (dup) return { ...dup, existing: true };
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
          // a target that the current best already meets would never alert: alert now
          if (next.alertBelow != null && next.alertBelow !== w.alertBelow && next.bestPrice != null && next.bestPrice <= next.alertBelow)
            addAlert(next, alertReasons(next, next.bestPrice, null), next.bestPrice, (next.bestTrip as Trip | null)?.tickets?.[0]?.booking_url ?? null);
          return next;
        }
        if (method === "DELETE") {
          write("watches", read<Watch[]>("watches", []).filter((x) => x.id !== id));
          remove(`obs.${id}`);
          // its alerts go with it (the server cascades the same way)
          write("alerts", read<Alert[]>("alerts", []).filter((a) => a.watchId !== id));
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
      if (method === "PATCH") {
        // the whole streamed result, once every part is in
        const row = list.find((r) => r.id === id);
        const payload = b.payload as { trips?: Trip[] } | undefined;
        if (!row || row.kind !== "search" || !Array.isArray(payload?.trips)) throw new GuestError(404, "not found");
        const had = new Set(((row.payload as { trips?: Trip[] } | null)?.trips ?? []).map((t) => t.id));
        write("searches", list.map((r) => (r.id === id ? { ...r, payload } : r)));
        await feedGuestWatches("search", row.query, payload.trips.filter((t) => !had.has(t.id)), serverFetch);
        return { id };
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

