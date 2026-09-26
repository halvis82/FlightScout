"use client";
import { afterGuestEngineCall, guestApi, GuestError, guestSettings, isGuestRoute } from "./guest";
import { localEngine, localRunnerActive, runnerKnown } from "./local-runner";
import type { SellerRule } from "./db/schema";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

type Init = { method?: string; body?: unknown; signal?: AbortSignal };

// Exchange rates change daily: one request per page load serves everyone.
let fxPromise: Promise<unknown> | null = null;

function serverFetch<T = unknown>(path: string, init?: Init): Promise<T> {
  if (path === "/fx" && !init?.body && (init?.method ?? "GET") === "GET") {
    fxPromise ??= rawFetch("/fx").catch((e) => {
      fxPromise = null;
      throw e;
    });
    return fxPromise as Promise<T>;
  }
  return rawFetch<T>(path, init);
}

async function rawFetch<T = unknown>(path: string, init?: Init): Promise<T> {
  const res = await fetch(path.startsWith("/api") ? path : `/api/v1${path}`, {
    method: init?.method ?? (init?.body !== undefined ? "POST" : "GET"),
    headers: init?.body !== undefined ? { "content-type": "application/json" } : undefined,
    body: init?.body !== undefined ? JSON.stringify(init.body) : undefined,
    signal: init?.signal,
    credentials: "same-origin",
  });
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) throw new ApiError(res.status, (data as { error?: string })?.error ?? res.statusText);
  return data as T;
}

// Resolved once per page load: is this visitor signed in? Guests get their
// data from localStorage through the guest router.
type MeLite = { user: unknown; settings?: { sellerRules?: SellerRule[] } };
let mePromise: Promise<MeLite | null> | null = null;
let meUnread = false; // mePromise hasn't been handed to a GET /me caller yet
function loadMe() {
  if (!mePromise) {
    mePromise = serverFetch<MeLite>("/me").catch(() => null);
    meUnread = true;
  }
  return mePromise;
}
export function isGuest(): Promise<boolean> {
  return loadMe().then((m) => (m ? !m.user : false));
}

const ENGINE_KINDS = new Set(["/search", "/plan", "/explore", "/dates", "/trip", "/multicity"]);

function rulesToEngine(rules: SellerRule[]) {
  const blocked = rules.filter((r) => r.mode === "block");
  return blocked.length ? Object.fromEntries(blocked.map((r) => [r.seller, r.mode])) : undefined;
}

// Engine call through the user's local runner. Mirrors the server proxy:
// seller rules become `seller_rules`, results are saved to history (and feed
// watches) through /results for signed in users, or locally for guests.
// Fares the website has seen, as layover hints for smart routes run here.
async function planHints(p: Record<string, unknown>): Promise<Record<string, unknown>> {
  const o = Array.isArray(p.origins) ? p.origins[0] : null;
  const d = Array.isArray(p.destinations) ? p.destinations[0] : null;
  const lo = typeof p.depart_start === "string" ? p.depart_start : null;
  if (!o || !d || !lo) return {};
  const hi = typeof p.depart_end === "string" && p.depart_end >= lo ? p.depart_end : lo;
  const to = new Date(Date.parse(hi) + 4 * 86400_000).toISOString().slice(0, 10);
  try {
    return await rawFetch<Record<string, unknown>>(`/fares?origin=${o}&destination=${d}&from=${lo}&to=${to}`);
  } catch {
    return {};
  }
}

// For the guest router's own engine calls (watch checks): the visitor's runner
// when it's connected (their IP, no server limits), else the server.
const engineOrServer: typeof serverFetch = async <T,>(path: string, init?: Init) => {
  const p = path.split("?")[0];
  if (ENGINE_KINDS.has(p) && localRunnerActive() && init?.body && typeof init.body === "object") {
    try {
      const body = { ...(init.body as Record<string, unknown>) };
      delete body.sellerRules;
      const rules = (init.body as { sellerRules?: SellerRule[] }).sellerRules;
      const sr = rules ? rulesToEngine(rules) : undefined;
      if (sr) body.seller_rules = sr;
      return (await localEngine(p.slice(1), body)) as T;
    } catch {
      /* the server below */
    }
  }
  return serverFetch<T>(path, init);
};

async function viaLocalRunner<T>(p: string, body: Record<string, unknown>, guest: boolean, signal?: AbortSignal): Promise<T> {
  const kind = p.slice(1);
  const quiet = body.quiet === true || (typeof body.part === "number" && body.part > 0);
  const query = { ...body };
  delete query.quiet;
  delete query.sellerRules;
  delete query.part; // stored like the server stores it
  const payload: Record<string, unknown> = { ...query };
  if ((kind === "search" || kind === "plan") && !payload.seller_rules) {
    const rules = guest ? guestSettings().sellerRules : ((await loadMe())?.settings?.sellerRules ?? []);
    const sr = rulesToEngine(rules);
    if (sr) payload.seller_rules = sr;
  }
  if (kind === "plan") Object.assign(payload, await planHints(payload));
  const result = await localEngine(kind, payload, signal);
  if (quiet) return { ...result, search_id: null, watches_updated: 0, via: "local" } as T;
  if (guest) {
    let id: number | null = null;
    try {
      id = await afterGuestEngineCall(kind, query, result, serverFetch);
    } catch {}
    return { ...result, search_id: id, watches_updated: 0, via: "local" } as T;
  }
  let saved: { id?: number; watchesUpdated?: number } = {};
  try {
    saved = await serverFetch("/results", { body: { kind, query, payload: result, origin: "local" } });
  } catch {}
  return { ...result, search_id: saved.id ?? null, watches_updated: saved.watchesUpdated ?? 0, via: "local" } as T;
}

export async function api<T = unknown>(path: string, init?: Init): Promise<T> {
  const method = init?.method ?? (init?.body !== undefined ? "POST" : "GET");
  const p = path.split("?")[0];
  if (p === "/settings" && method !== "GET") mePromise = null;
  // who is signed in: fetched once, and this request primes the cache used by isGuest()
  if (path === "/me" && method === "GET") {
    // the first reader shares the request isGuest() already made; later ones (refreshes) fetch again
    if (meUnread && mePromise) {
      meUnread = false;
      const m = await mePromise;
      if (m) return m as T;
    }
    meUnread = false;
    const me = serverFetch<MeLite>("/me");
    mePromise = me.catch(() => null);
    return me as Promise<T>;
  }
  const external = !path.startsWith("/api");
  const guest = external && (await isGuest());

  if (external && ENGINE_KINDS.has(p)) await runnerKnown();
  if (external && ENGINE_KINDS.has(p) && localRunnerActive()) {
    try {
      return await viaLocalRunner<T>(p, (init?.body ?? {}) as Record<string, unknown>, guest, init?.signal);
    } catch (e) {
      if ((e as Error).name === "AbortError") throw e;
      // any local failure falls back to the server proxy below
    }
  }

  if (guest) {
    // a result found here, for a guest's own history (and watches)
    if (p === "/results" && method === "POST") {
      const b = (init?.body ?? {}) as { kind: string; query: Record<string, unknown>; payload: Record<string, unknown> };
      const id = await afterGuestEngineCall(b.kind, b.query, b.payload, serverFetch).catch(() => null);
      return { id } as T;
    }
    if (isGuestRoute(path)) {
      try {
        return (await guestApi(path, method, init?.body, engineOrServer)) as T;
      } catch (e) {
        if (e instanceof GuestError) throw new ApiError(e.status, e.message);
        throw e;
      }
    }
    // guests send their seller rules along, signed in users have them saved
    const body =
      (p === "/search" || p === "/plan") && init?.body && typeof init.body === "object"
        ? { sellerRules: guestSettings().sellerRules, ...(init.body as object) }
        : init?.body;
    const res = await serverFetch<T>(path, { ...init, body });
    const b = (init?.body ?? {}) as Record<string, unknown>;
    if (ENGINE_KINDS.has(p) && b.quiet !== true && !(typeof b.part === "number" && b.part > 0)) {
      try {
        const q = { ...b };
        delete q.part; // stored like the server stores it
        const id = await afterGuestEngineCall(p.slice(1), q, res as Record<string, unknown>, serverFetch);
        if (id != null) (res as Record<string, unknown>).search_id = id;
      } catch {}
    }
    return res;
  }
  return serverFetch<T>(path, init);
}

export const fetcher = <T,>(path: string) => api<T>(path);
