"use client";
// The "local runner": `flightscout serve` on the user's own machine serves the
// engine API at http://127.0.0.1:8787 in local mode (no key, CORS for this
// app). When it is up, engine calls go straight from the browser to it, so
// searches use the user's home IP and skip the server's rate limits.
// Installed with `flightscout serve --install` it starts on demand (the OS
// holds the port and starts it on the first request, about 1 to 2 s) and
// exits after two quiet hours, so probes must allow for a cold start and
// must not keep it awake.

import { useSyncExternalStore } from "react";

export const LOCAL_RUNNER_URL = "http://127.0.0.1:8787";
const OFF_KEY = "fs.localRunner.off";

export type Lifecycle = { started_at: number; idle_minutes: number; idle_expires_at: number | null; active_requests: number };
type State = { available: boolean; version: string | null; checked: boolean; disabled: boolean; outdated: boolean;
  lifecycle: Lifecycle | null; probing: boolean; standby: boolean };

let state: State = { available: false, version: null, checked: false, disabled: false, outdated: false, lifecycle: null, probing: false, standby: false };

// The runner's "api" level this website needs (engine/src/flightscout/api.py
// API_LEVEL). An older runner answers but would reject searches, so it's
// skipped and Settings asks for an update.
const MIN_API = 3;
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

// Chrome (142+) asks once before a public site may reach this computer
// ("Local network access"). Probing when the answer is still open would show
// that prompt to every visitor, so unknown visitors are only probed when it
// was already granted; Settings has a Connect button that asks on purpose.
export type LocalAccess = "granted" | "prompt" | "denied" | "unsupported";
export async function localAccess(): Promise<LocalAccess> {
  try {
    const s = await navigator.permissions.query({ name: "local-network-access" as PermissionName });
    return s.state as LocalAccess;
  } catch {
    return "unsupported"; // browsers without the permission just connect
  }
}

export function localRunnerActive() {
  return state.available && !state.disabled;
}

// Before the first engine call on a page: if this browser has used a runner
// before and the check is still running, wait for it (the first search of a
// page load otherwise goes to the server). Returns at once for everyone else.
export async function runnerKnown(): Promise<void> {
  if (typeof window === "undefined" || state.disabled || state.available) return;
  if (lsGet(SEEN) !== "1") return;
  await (inflight ?? probeLocalRunner());
}

// Settings' Connect button: probing from a click lets Chrome ask for access.
export async function connectLocalRunner(): Promise<boolean> {
  setLocalRunnerDisabled(false);
  const ok = await probeLocalRunner();
  if (ok) lsSet(SEEN, "1");
  return ok;
}

let inflight: Promise<boolean> | null = null;

// Available only when /health says local === true. The dev engine on the same
// port answers {ok:true} without `local`, or 401, and is ignored.
export function probeLocalRunner(): Promise<boolean> {
  if (typeof window === "undefined") return Promise.resolve(false);
  inflight ??= (async () => {
    emit({ probing: true });
    try {
      const ctrl = new AbortController();
      // a known runner may be starting on demand; an unknown port fails fast anyway
      const t = setTimeout(() => ctrl.abort(), 8000);
      const res = await fetch(`${LOCAL_RUNNER_URL}/health`, { signal: ctrl.signal, cache: "no-store", mode: "cors" }).finally(() => clearTimeout(t));
      const j = res.ok ? ((await res.json()) as { ok?: boolean; local?: boolean; version?: string; api?: number; lifecycle?: Lifecycle }) : null;
      const outdated = j?.local === true && (j.api ?? 1) < MIN_API;
      const ok = j?.local === true && !outdated;
      emit({ available: ok, version: j?.local ? (j?.version ?? null) : null, checked: true, disabled: readDisabled(), outdated, lifecycle: j?.local ? (j.lifecycle ?? null) : null, standby: false });
      return ok;
    } catch {
      emit({ available: false, version: null, checked: true, disabled: readDisabled(), outdated: false, lifecycle: null, standby: false });
      return false;
    } finally {
      inflight = null;
      emit({ probing: false });
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

// Check only a running runner while visible. Once its advertised idle deadline
// passes, stop probing: opening the socket would start it again. Explicit
// Connect and a new search can wake it. Health checks never extend the deadline.
export function startLocalRunnerProbe() {
  if (started || typeof window === "undefined") return;
  started = true;
  emit({ disabled: readDisabled() });
  const seen = lsGet(SEEN) === "1";
  const lastMiss = Number(lsGet(MISS) ?? 0);
  const check = async () => {
    const ok = await probeLocalRunner();
    if (ok) lsSet(SEEN, "1");
    else lsSet(MISS, String(Date.now()));
  };
  if (!state.disabled && (seen || Date.now() - lastMiss >= 24 * 3600_000)) {
    localAccess().then((a) => {
      if (a === "granted" || a === "unsupported") return check();
      emit({ checked: true });
    });
  } else emit({ checked: true });
  setInterval(() => {
    if (!state.available || !state.lifecycle || state.probing || localRequests) return;
    const deadline = state.lifecycle?.idle_expires_at;
    if (deadline && Date.now() >= deadline * 1000) {
      emit({ available: false, standby: true });
      return;
    }
    if (!state.disabled && document.visibilityState === "visible") void check();
  }, 30_000);
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
// How long the runner may take before the search falls back to the server
// (its own deadlines are 45 to 90 s per source; plans and trips run longer).
const RUNNER_TIMEOUT_S: Record<string, number> = { search: 150, dates: 90, explore: 120, plan: 240, trip: 300, multicity: 300 };

let localRequests = 0;

export async function localEngine(kind: string, payload: Record<string, unknown>, signal?: AbortSignal) {
  const limit = AbortSignal.timeout((RUNNER_TIMEOUT_S[kind] ?? 150) * 1000);
  localRequests++;
  if (state.lifecycle) emit({ lifecycle: { ...state.lifecycle, active_requests: localRequests, idle_expires_at: null } });
  try {
    const res = await fetch(`${LOCAL_RUNNER_URL}/${kind}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
      signal: signal ? AbortSignal.any([signal, limit]) : limit,
      cache: "no-store",
    });
    const text = await res.text();
    if (!res.ok) throw new Error(`local runner ${res.status}: ${text.slice(0, 200)}`);
    return normalizeEngine(kind, JSON.parse(text));
  } catch (e) {
    // Do not label an aborted search as a disconnected runner.
    if (!signal?.aborted) emit({ available: false, lifecycle: null });
    throw e;
  } finally {
    localRequests--;
    if (state.lifecycle) emit({ lifecycle: { ...state.lifecycle, active_requests: localRequests,
      idle_expires_at: !localRequests && state.lifecycle.idle_minutes ? Date.now() / 1000 + state.lifecycle.idle_minutes * 60 : null,
    } });
  }
}
