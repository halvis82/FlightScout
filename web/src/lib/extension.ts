"use client";
// FlightScout Helper (browser extension, /extension in the repo): when it's
// installed, Google Flights pages are fetched by the visitor's own browser
// (their IP), and the server only parses them. See engine browser_fetch.py.

import { useSyncExternalStore } from "react";

let version: string | null = null;
const listeners = new Set<() => void>();
const pending = new Map<string, (pages: Record<string, unknown>) => void>();

if (typeof window !== "undefined") {
  window.addEventListener("message", (e) => {
    if (e.source !== window || e.origin !== window.location.origin) return;
    const m = e.data as { source?: string; type?: string; version?: string; id?: string; pages?: Record<string, unknown> };
    if (m?.source !== "flightscout-ext") return;
    if (m.type === "hello" && m.version) {
      version = m.version;
      listeners.forEach((l) => l());
    }
    if (m.type === "pages" && m.id) {
      pending.get(m.id)?.(m.pages ?? {});
      pending.delete(m.id);
    }
  });
  window.postMessage({ source: "flightscout-page", type: "ping" }, window.location.origin);
}

export const extensionVersion = () => version;

export function useExtension() {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => version,
    () => null,
  );
}

function fetchPages(urls: string[], timeoutMs = 45_000): Promise<Record<string, unknown>> {
  const id = Math.random().toString(36).slice(2);
  return new Promise((resolve, reject) => {
    const t = setTimeout(() => {
      pending.delete(id);
      reject(new Error("extension timed out"));
    }, timeoutMs);
    pending.set(id, (pages) => {
      clearTimeout(t);
      resolve(pages);
    });
    window.postMessage({ source: "flightscout-page", type: "fetchPages", id, urls }, window.location.origin);
  });
}

// Run a Google search with pages from this browser: the server answers
// {need: [urls]} until it has every page, then the normal SearchResult.
export async function browserGoogleSearch<T>(
  query: Record<string, unknown>,
  post: (body: Record<string, unknown>) => Promise<T & { need?: string[] }>,
): Promise<T> {
  const pages: Record<string, unknown> = {};
  for (let round = 0; round < 4; round++) {
    const r = await post({ ...query, pages });
    if (!r.need?.length) return r;
    const got = await fetchPages(r.need);
    const missing = r.need.filter((u) => !(u in got));
    if (missing.length === r.need.length) throw new Error("the extension couldn't load Google Flights");
    Object.assign(pages, got);
    for (const u of missing) pages[u] = [null, null, null, null, null, null, null, null]; // count as "no flights"
  }
  throw new Error("too many rounds");
}
