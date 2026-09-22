"use client";
// Tiny global stores: which slide-over panel is open, and toasts.
import { useSyncExternalStore } from "react";

function store<T>(initial: T) {
  let value = initial;
  const ls = new Set<() => void>();
  return {
    get: () => value,
    set: (v: T) => {
      value = v;
      ls.forEach((l) => l());
    },
    use: () =>
      useSyncExternalStore(
        (cb) => {
          ls.add(cb);
          return () => ls.delete(cb);
        },
        () => value,
        () => initial,
      ),
  };
}

export type Panel = "watchlist" | null;
export const panelStore = store<Panel>(null);
export const openPanel = (p: Panel) => panelStore.set(p);

export type Toast = { id: number; text: string; action?: { label: string; href?: string; onClick?: () => void }; tone?: "good" | "bad" };
export const toastStore = store<Toast[]>([]);
let seq = 0;
export function toast(t: Omit<Toast, "id">, ms = 5000) {
  const id = ++seq;
  toastStore.set([...toastStore.get(), { ...t, id }]);
  setTimeout(() => toastStore.set(toastStore.get().filter((x) => x.id !== id)), ms);
}
