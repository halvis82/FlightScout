"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import useSWR from "swr";
import { ArrowDownRight, ArrowUpRight, Bell, Pause, Play, Plus, RefreshCw, Star, X } from "lucide-react";
import { useApp } from "./app-context";
import { RouteText } from "./place";
import { Sparkline } from "./sparkline";
import { openPanel, panelStore } from "./stores";
import { useWatchDialog } from "./watch-dialog";
import { PlainButton, Badge, Button, Spinner } from "./ui";
import { api, fetcher } from "@/lib/client";
import { formatDate, relativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { WatchRow } from "@/lib/watch-types";

type Alert = { id: number; message: string; watchId: number | null; createdAt: string; readAt: string | null };

export function useWatches() {
  return useSWR<WatchRow[]>("/watches", fetcher, { revalidateOnFocus: false });
}

export function useAlerts() {
  return useSWR<{ alerts: Alert[]; unread: number }>("/alerts", fetcher, { refreshInterval: 120_000 });
}

// Header button: star with the number of watches, dot for unread alerts.
export function WatchlistButton() {
  const { data } = useWatches();
  const { data: alerts } = useAlerts();
  const n = data?.length ?? 0;
  return (
    <button
      onClick={() => openPanel(panelStore.get() === "watchlist" ? null : "watchlist")}
      className="relative inline-flex h-9 items-center gap-1.5 rounded-lg px-2.5 text-sm font-medium text-muted hover:bg-surface-2 hover:text-fg"
      aria-label={`Watchlist, ${n} routes`}
      title="Watchlist"
    >
      <Star className="size-4" />
      <span className="hidden sm:inline">Watchlist</span>
      {n > 0 && <span className="rounded-full bg-surface-2 px-1.5 text-[11px] font-semibold text-fg tabular-nums">{n}</span>}
      {!!alerts?.unread && <span className="absolute top-1.5 left-6 size-2 rounded-full bg-bad ring-2 ring-surface" />}
    </button>
  );
}

export function WatchlistPanel() {
  const open = panelStore.use() === "watchlist";
  const { data, mutate, isLoading } = useWatches();
  const { data: alerts, mutate: mutateAlerts } = useAlerts();
  const watch = useWatchDialog();
  const [checking, setChecking] = useState<number | null>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && openPanel(null);
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  async function check(id: number) {
    setChecking(id);
    try {
      await api(`/watches/${id}/check`, { body: {} });
    } catch {}
    setChecking(null);
    mutate();
    mutateAlerts();
  }

  const unread = alerts?.alerts.filter((a) => !a.readAt) ?? [];

  return (
    <>
      <div
        className={cn("fixed inset-0 z-50 bg-black/30 transition-opacity", open ? "opacity-100" : "pointer-events-none opacity-0")}
        onClick={() => openPanel(null)}
        aria-hidden
      />
      <aside
        className={cn(
          "fixed inset-y-0 right-0 z-50 flex w-full max-w-[440px] flex-col border-l border-border bg-bg shadow-[var(--shadow-lg)] transition-transform duration-200",
          open ? "translate-x-0" : "pointer-events-none translate-x-full",
        )}
        aria-label="Watchlist"
        aria-hidden={!open}
      >
        <div className="flex items-center justify-between gap-2 border-b border-border bg-surface px-4 py-3">
          <div>
            <h2 className="flex items-center gap-2 text-base font-semibold">
              <Star className="size-4 text-accent" /> Watchlist
            </h2>
            <p className="text-xs text-muted">Checked twice a day. Use Watch on any search or result to add one.</p>
          </div>
          <div className="flex items-center gap-1">
            <Button size="sm" variant="soft" onClick={() => watch.open()}>
              <Plus className="size-3.5" /> New
            </Button>
            <button onClick={() => openPanel(null)} className="rounded-lg p-2 text-muted hover:bg-surface-2 hover:text-fg" aria-label="Close watchlist">
              <X className="size-4" />
            </button>
          </div>
        </div>
        <div className="flex-1 space-y-3 overflow-y-auto p-3">
          {unread.length > 0 && (
            <div className="rounded-xl border border-accent/20 bg-accent-soft/50 p-3">
              <div className="mb-1.5 flex items-center justify-between">
                <span className="flex items-center gap-1.5 text-xs font-semibold text-accent">
                  <Bell className="size-3.5" /> Price alerts
                </span>
                <PlainButton
                  className="text-xs text-accent hover:underline"
                  onClick={async () => {
                    await api("/alerts", { body: { all: true } });
                    mutateAlerts();
                  }}
                >
                  Mark all read
                </PlainButton>
              </div>
              <ul className="space-y-1">
                {unread.slice(0, 5).map((a) => (
                  <li key={a.id}>
                    <Link
                      href={a.watchId ? `/watches/${a.watchId}` : "/"}
                      onClick={() => {
                        openPanel(null);
                        api("/alerts", { body: { ids: [a.id] } }).then(() => mutateAlerts());
                      }}
                      className="block text-sm hover:underline"
                    >
                      {a.message} <span className="text-xs text-faint">{relativeTime(a.createdAt)}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {isLoading && (
            <div className="grid h-32 place-items-center text-muted">
              <Spinner />
            </div>
          )}
          {data && !data.length && (
            <div className="rounded-2xl border border-dashed border-border-strong/70 px-5 py-10 text-center">
              <div className="mx-auto mb-3 grid size-11 place-items-center rounded-full bg-accent-soft text-accent">
                <Star className="size-5" />
              </div>
              <div className="font-semibold">No watched routes yet</div>
              <p className="mx-auto mt-1 max-w-xs text-sm text-muted">
                Tap the star on any flight result to track its price. FlightScout records every check so you can see when to book.
              </p>
            </div>
          )}
          {data?.map((w) => (
            <WatchRowCard
              key={w.id}
              w={w}
              checking={checking === w.id}
              onCheck={() => check(w.id)}
              onToggle={async () => {
                await api(`/watches/${w.id}`, { method: "PATCH", body: { active: !w.active } });
                mutate();
              }}
            />
          ))}
        </div>
      </aside>
      {watch.element}
    </>
  );
}

function WatchRowCard({ w, onCheck, onToggle, checking }: { w: WatchRow; onCheck: () => void; onToggle: () => void; checking: boolean }) {
  const { money } = useApp();
  const delta = w.bestPrice != null && w.prevPrice != null ? w.bestPrice - w.prevPrice : null;
  const pct = delta != null && w.prevPrice ? (delta / w.prevPrice) * 100 : null;
  return (
    <div className={cn("rounded-2xl border border-border bg-surface p-3 shadow-[var(--shadow)] transition-colors hover:border-border-strong", !w.active && "opacity-60")}>
      <Link href={`/watches/${w.id}`} onClick={() => openPanel(null)} className="block">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            {w.tripType === "multicity" ? (
              <span className="text-sm font-medium">{w.name}</span>
            ) : (
              <RouteText codes={[w.origins[0], w.destinations[0]]} roundTrip={w.tripType === "roundtrip"} className="text-sm" />
            )}
            <div className="mt-0.5 text-xs text-muted">
              {formatDate(w.departStart, false)}
              {w.departEnd !== w.departStart && ` to ${formatDate(w.departEnd, false)}`}
              {w.tripType === "roundtrip" && w.nightsMin != null && ` · ${w.nightsMin}${w.nightsMax && w.nightsMax !== w.nightsMin ? `–${w.nightsMax}` : ""} nights`}
              {w.origins.length + w.destinations.length > 2 && ` · ${w.origins.length + w.destinations.length} airports`}
            </div>
          </div>
          <div className="shrink-0 text-right">
            <div className="text-lg font-semibold tabular-nums">{money(w.bestPrice, w.currency)}</div>
            {pct != null && Math.abs(pct) >= 0.5 ? (
              <span className={cn("inline-flex items-center text-xs font-medium", delta! < 0 ? "text-good" : "text-bad")}>
                {delta! < 0 ? <ArrowDownRight className="size-3.5" /> : <ArrowUpRight className="size-3.5" />}
                {Math.abs(pct).toFixed(0)}%
              </span>
            ) : (
              <span className="text-xs text-faint">{w.lowestPrice != null ? `low ${money(w.lowestPrice, w.currency)}` : "not checked"}</span>
            )}
          </div>
        </div>
        <div className="mt-2 h-8">
          <Sparkline data={(w.sparkline ?? []).map((p) => p.price)} className="h-8 w-full" />
        </div>
      </Link>
      <div className="mt-2 flex items-center justify-between border-t border-border pt-2 text-xs text-muted">
        <span className="flex items-center gap-1.5">
          checked {relativeTime(w.lastCheckedAt)}
          {!w.active && <Badge>Paused</Badge>}
          {w.includeSplit && <Badge tone="info">Smart</Badge>}
        </span>
        <div className="flex gap-0.5">
          <button onClick={onToggle} className="rounded-md p-1.5 hover:bg-surface-2 hover:text-fg" title={w.active ? "Pause" : "Resume"} aria-label={w.active ? "Pause" : "Resume"}>
            {w.active ? <Pause className="size-3.5" /> : <Play className="size-3.5" />}
          </button>
          <button onClick={onCheck} disabled={checking} className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 hover:bg-surface-2 hover:text-fg" title="Check now">
            {checking ? <Spinner className="size-3.5" /> : <RefreshCw className="size-3.5" />} Check now
          </button>
        </div>
      </div>
    </div>
  );
}
