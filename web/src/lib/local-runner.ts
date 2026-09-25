"use client";
// The "local runner": `flightscout serve` on the user's own machine serves the
// engine API at http://127.0.0.1:8787 in local mode (no key, CORS for this
// app). When it is up, engine calls go straight from the browser to it, so
// searches use the user's home IP and skip the server's rate limits.
// Installed with `flightscout serve --install` it starts on demand (the OS
// holds the port and starts it on the first request, about 1 to 2 s) and
// exits after 10 quiet minutes, so probes must allow for a cold start and
// must not keep it awake.

import { useSyncExternalStore } from "react";

export const LOCAL_RUNNER_URL = "http://127.0.0.1:8787";
const OFF_KEY = "fs.localRunner.off";

type State = { available: boolean; version: string | null; checked: boolean; disabled: boolean };

let state: State = { available: false, version: null, checked: false, disabled: false };
const SERVER_STATE: State = state;
const listeners = new Set<() => void>();

function emit(next: Partial<State>) {
  state = { ...state, ...next };
  listeners.forEach((l) => l());
}

function readDisabled() {
  try {
    return localStorage.getItem(OFF_KEY) === "1";
  } catch {
    return false;
  }
}

export function setLocalRunnerDisabled(off: boolean) {
  try {
    if (off) localStorage.setItem(OFF_KEY, "1");
    else localStorage.removeItem(OFF_KEY);
  } catch {}
  emit({ disabled: off });
}

export function localRunnerActive() {
  return state.available && !state.disabled;
}

let inflight: Promise<boolean> | null = null;

// Available only when /health says local === true. The dev engine on the same
// port answers {ok:true} without `local`, or 401, and is ignored.
export function probeLocalRunner(): Promise<boolean> {
  if (typeof window === "undefined") return Promise.resolve(false);
  inflight ??= (async () => {
    const disabled = readDisabled();
    try {
      const ctrl = new AbortController();
      // a known runner may be starting on demand; an unknown port fails fast anyway
      const t = setTimeout(() => ctrl.abort(), lsGet(SEEN) === "1" ? 8000 : 1500);
      const res = await fetch(`${LOCAL_RUNNER_URL}/health`, { signal: ctrl.signal, cache: "no-store", mode: "cors" }).finally(() => clearTimeout(t));
      const j = res.ok ? ((await res.json()) as { ok?: boolean; local?: boolean; version?: string }) : null;
      const ok = j?.local === true;
      emit({ available: ok, version: ok ? (j?.version ?? null) : null, checked: true, disabled });
      return ok;
    } catch {
      emit({ available: false, version: null, checked: true, disabled });
      return false;
    } finally {
      inflight = null;
    }
  })();
  return inflight;
}

let started = false;
const SEEN = "fs.runner.seen"; // the runner has answered on this browser before
const MISS = "fs.runner.miss"; // last time a probe found nothing

function lsGet(k: string) {
  try {
    return localStorage.getItem(k);
  } catch {
    return null;
  }
}
function lsSet(k: string, v: string) {
  try {
    localStorage.setItem(k, v);
  } catch {
    /* ignore */
  }
}

// Browsers log a console error for every failed probe, so people who never
// used the runner are checked at most once a day (Settings can re-check any
// time). People who do are checked on page load and when they come back to
// the tab (at most every 5 minutes): no polling, so an on demand runner can
// go back to sleep. If it's gone at search time, searches fall back to the
// server by themselves.
async function probeAndRemember() {
  const ok = await probeLocalRunner();
  if (ok) lsSet(SEEN, "1");
  else lsSet(MISS, String(Date.now()));
  return ok;
}

export function startLocalRunnerProbe() {
  if (started || typeof window === "undefined") return;
  started = true;
  const seen = lsGet(SEEN) === "1";
  const lastMiss = Number(lsGet(MISS) ?? 0);
  if (!seen && Date.now() - lastMiss < 24 * 3600_000) {
    emit({ ...state, checked: true });
    return;
  }
  let last = Date.now();
  probeAndRemember().then((ok) => {
    if (!ok && !seen) return;
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible" && Date.now() - last > 5 * 60_000) {
        last = Date.now();
        probeLocalRunner();
      }
    });
  });
}

export function useLocalRunner() {
  const s = useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => state,
    () => SERVER_STATE,
  );
  return { ...s, active: s.available && !s.disabled };
}

// Same response mapping as the server proxy (src/lib/engine-proxy.ts).
export function normalizeEngine(kind: string, raw: unknown): Record<string, unknown> {
  if (Array.isArray(raw)) return { items: raw, errors: {} };
  const r = raw as Record<string, unknown>;
  if (kind === "explore" && Array.isArray(r.destinations)) return { items: r.destinations, errors: r.errors ?? {} };
  return r;
}

// POST an engine call to the local runner. Throws on any failure so callers
// can fall back to the server.
export async function localEngine(kind: string, payload: Record<string, unknown>, signal?: AbortSignal) {
  const res = await fetch(`${LOCAL_RUNNER_URL}/${kind}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
    signal,
    cache: "no-store",
  });
  const text = await res.text();
  if (!res.ok) throw new Error(`local runner ${res.status}: ${text.slice(0, 200)}`);
  return normalizeEngine(kind, JSON.parse(text));
}
