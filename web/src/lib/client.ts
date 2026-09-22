"use client";
import { afterGuestEngineCall, guestApi, GuestError, guestSettings, isGuestRoute } from "./guest";

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
let modePromise: Promise<boolean> | null = null;
export function isGuest(): Promise<boolean> {
  modePromise ??= serverFetch<{ user: unknown }>("/me")
    .then((m) => !m.user)
    .catch(() => false);
  return modePromise;
}

const ENGINE_KINDS = new Set(["/search", "/plan", "/explore", "/dates", "/trip"]);

export async function api<T = unknown>(path: string, init?: Init): Promise<T> {
  const method = init?.method ?? (init?.body !== undefined ? "POST" : "GET");
  if (!path.startsWith("/api") && (await isGuest())) {
    if (isGuestRoute(path)) {
      try {
        return (await guestApi(path, method, init?.body, serverFetch)) as T;
      } catch (e) {
        if (e instanceof GuestError) throw new ApiError(e.status, e.message);
        throw e;
      }
    }
    const p = path.split("?")[0];
    // guests send their seller rules along, signed in users have them saved
    const body =
      (p === "/search" || p === "/plan") && init?.body && typeof init.body === "object"
        ? { sellerRules: guestSettings().sellerRules, ...(init.body as object) }
        : init?.body;
    const res = await serverFetch<T>(path, { ...init, body });
    if (ENGINE_KINDS.has(p)) {
      try {
        await afterGuestEngineCall(p.slice(1), (init?.body ?? {}) as Record<string, unknown>, res as Record<string, unknown>, serverFetch);
      } catch {}
    }
    return res;
  }
  return serverFetch<T>(path, init);
}

export const fetcher = <T,>(path: string) => api<T>(path);
