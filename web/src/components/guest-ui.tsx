"use client";
import { useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { X } from "lucide-react";
import { useApp } from "./app-context";
import { Dialog } from "./dialog";
import { Button, ErrorNote } from "./ui";
import { api } from "@/lib/client";
import { clearGuestData, guestSnapshot, hasGuestData } from "@/lib/guest";

const DISMISS_KEY = "fs.bannerDismissed";
const listeners = new Set<() => void>();
const subscribe = (cb: () => void) => {
  listeners.add(cb);
  return () => listeners.delete(cb);
};
const readFlag = (k: string) => {
  try {
    return localStorage.getItem(k) === "1";
  } catch {
    return false;
  }
};
const setFlag = (k: string) => {
  try {
    localStorage.setItem(k, "1");
  } catch {}
  listeners.forEach((l) => l());
};

export function GuestBanner() {
  const { me } = useApp();
  const dismissed = useSyncExternalStore(subscribe, () => readFlag(DISMISS_KEY), () => true);
  if (!me?.guest || dismissed) return null;
  return (
    <div className="border-b border-border bg-accent-soft/60">
      <div className="mx-auto flex max-w-7xl items-center gap-3 px-4 py-1.5 text-xs">
        <span className="min-w-0 flex-1 text-muted">
          You&apos;re using FlightScout as a guest. Places, watches and history are saved in this browser. Signing in adds daily background
          price tracking, alerts, sync across devices and CLI and agent access.
        </span>
        <Link href="/login" className="shrink-0 font-medium text-accent hover:underline">
          Sign in
        </Link>
        <button onClick={() => setFlag(DISMISS_KEY)} className="shrink-0 rounded p-0.5 text-muted hover:text-fg" aria-label="Dismiss">
          <X className="size-3.5" />
        </button>
      </div>
    </div>
  );
}

// Shown once after signing in when this browser still has guest data.
export function ImportGuestData() {
  const { me, refreshMe, refreshPlaces } = useApp();
  const skipped = useSyncExternalStore(subscribe, () => readFlag("fs.importSkipped"), () => true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const open = Boolean(me?.user) && !skipped && !done && hasGuestData();
  if (!open) return null;
  const snap = guestSnapshot();

  async function run() {
    setBusy(true);
    setErr(null);
    try {
      const s = snap.settings;
      const current = me!.settings!;
      await api("/settings", {
        method: "PATCH",
        body: {
          currency: s.currency,
          planner: s.planner,
          sellerRules: [...current.sellerRules, ...s.sellerRules.filter((r) => !current.sellerRules.some((c) => c.seller === r.seller))],
          defaultOrigins: [...new Set([...current.defaultOrigins, ...s.defaultOrigins])],
        },
      });
      const existing = await api<{ codes: string[]; label: string }[]>("/places");
      for (const p of snap.places) {
        if (existing.some((e) => e.label === p.label && e.codes.join() === p.codes.join())) continue;
        await api("/places", { body: { label: p.label, codes: p.codes, kind: p.kind } });
      }
      for (const { watch: w, observations } of snap.watches) {
        const row = await api<{ id: number }>("/watches", {
          body: {
            name: w.name,
            origins: w.origins,
            destinations: w.destinations,
            trip_type: w.tripType,
            depart_start: w.departStart,
            depart_end: w.departEnd,
            nights_min: w.nightsMin,
            nights_max: w.nightsMax,
            cabin: w.cabin,
            adults: w.adults,
            max_stops: w.maxStops,
            currency: w.currency,
            include_split: w.includeSplit,
            alert_below: w.alertBelow,
            alert_drop_pct: w.alertDropPct,
            active: w.active,
            notes: w.notes,
          },
        });
        for (let i = 0; i < observations.length; i += 500) {
          await api(`/watches/${row.id}/observations`, { body: observations.slice(i, i + 500) });
        }
      }
      for (const r of [...snap.searches].reverse()) {
        if (!r.payload) continue;
        await api("/results", { body: { kind: r.kind, query: r.query, payload: r.payload, origin: "web" } });
      }
      clearGuestData();
      setDone(true);
      await Promise.all([refreshMe(), refreshPlaces()]);
      location.reload();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open onClose={() => setFlag("fs.importSkipped")} title="Bring your guest data along?">
      <p className="text-sm text-muted">This browser has data from when you used FlightScout without signing in:</p>
      <ul className="my-3 space-y-1 text-sm">
        <li>{snap.places.length} saved places</li>
        <li>
          {snap.watches.length} watches with {snap.watches.reduce((n, w) => n + w.observations.length, 0)} recorded prices
        </li>
        <li>{snap.searches.filter((s) => s.payload).length} recent searches</li>
        <li>Your currency, smart route limits and seller rules</li>
      </ul>
      <p className="text-sm text-muted">Importing adds them to your account so they sync and get tracked daily. The local copy is removed afterwards.</p>
      {err && <div className="mt-3"><ErrorNote>{err}</ErrorNote></div>}
      <div className="mt-4 flex justify-between gap-2 border-t border-border pt-3">
        <Button
          variant="ghost"
          onClick={() => {
            if (confirm("Delete the guest data in this browser without importing it?")) {
              clearGuestData();
              setDone(true);
            }
          }}
        >
          Discard
        </Button>
        <div className="flex gap-2">
          <Button onClick={() => setFlag("fs.importSkipped")}>Not now</Button>
          <Button variant="primary" onClick={run} loading={busy}>
            Import into my account
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
