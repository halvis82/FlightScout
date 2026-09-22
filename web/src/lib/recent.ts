"use client";
// Recent searches kept in this browser (for guests and signed in users alike)
// to prefill the form and offer one click repeats.
import { useSyncExternalStore } from "react";

export type Recent = { from: string[]; to: string[]; tripType: "roundtrip" | "oneway"; depart: string; ret: string; at: number };

const KEY = "fs.recent";
const listeners = new Set<() => void>();
let snapshot: Recent[] | null = null;
const EMPTY: Recent[] = [];

function read(): Recent[] {
  if (snapshot) return snapshot;
  try {
    snapshot = JSON.parse(localStorage.getItem(KEY) ?? "[]") as Recent[];
  } catch {
    snapshot = [];
  }
  return snapshot;
}

export function recentSearches() {
  return read();
}

export function pushRecent(r: Omit<Recent, "at">) {
  const same = (x: Recent) => x.from.join() === r.from.join() && x.to.join() === r.to.join() && x.tripType === r.tripType;
  const next = [{ ...r, at: Date.now() }, ...read().filter((x) => !same(x as Recent))].slice(0, 10);
  snapshot = next;
  try {
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {}
  listeners.forEach((l) => l());
}

export function removeRecent(i: number) {
  const next = read().filter((_, j) => j !== i);
  snapshot = next;
  try {
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {}
  listeners.forEach((l) => l());
}

export function useRecent() {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    read,
    () => EMPTY,
  );
}
