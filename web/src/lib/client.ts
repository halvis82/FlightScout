"use client";
import { afterGuestEngineCall, guestApi, GuestError, guestSettings, isGuestRoute } from "./guest";
import { localEngine, localRunnerActive } from "./local-runner";
import type { SellerRule } from "./db/schema";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

type Init = { method?: string; body?: unknown; signal?: AbortSignal };

async function serverFetch<T = unknown>(path: string, init?: Init): Promise<T> {
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
function loadMe() {
  mePromise ??= serverFetch<MeLite>("/me").catch(() => null);
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
async function viaLocalRunner<T>(p: string, body: Record<string, unknown>, guest: boolean, signal?: AbortSignal): Promise<T> {
  const kind = p.slice(1);
  const quiet = body.quiet === true || (typeof body.part === "number" && body.part > 0);
  const query = { ...body };
  delete query.quiet;
  delete query.sellerRules;
  const payload: Record<string, unknown> = { ...query };
  if ((kind === "search" || kind === "plan") && !payload.seller_rules) {
    const rules = guest ? guestSettings().sellerRules : ((await loadMe())?.settings?.sellerRules ?? []);
    const sr = rulesToEngine(rules);
    if (sr) payload.seller_rules = sr;
  }
  const result = await localEngine(kind, payload, signal);
  if (quiet) return { ...result, search_id: null, watches_updated: 0, via: "local" } as T;
  if (guest) {
    try {
      await afterGuestEngineCall(kind, query, result, serverFetch);
    } catch {}
    return { ...result, search_id: null, watches_updated: 0, via: "local" } as T;
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
  const external = !path.startsWith("/api");
  const guest = external && (await isGuest());

  if (external && ENGINE_KINDS.has(p) && localRunnerActive()) {
    try {
      return await viaLocalRunner<T>(p, (init?.body ?? {}) as Record<string, unknown>, guest, init?.signal);
    } catch (e) {
      if ((e as Error).name === "AbortError") throw e;
      // any local failure falls back to the server proxy below
    }
  }

  if (guest) {
    if (isGuestRoute(path)) {
      try {
        return (await guestApi(path, method, init?.body, serverFetch)) as T;
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
        await afterGuestEngineCall(p.slice(1), b, res as Record<string, unknown>, serverFetch);
      } catch {}
    }
    return res;
  }
  return serverFetch<T>(path, init);
}

export const fetcher = <T,>(path: string) => api<T>(path);
