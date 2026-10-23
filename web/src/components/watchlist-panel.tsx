"use client";
import Link from "next/link";
import { useEffect } from "react";
import useSWR from "swr";
import { Bell, Plus, Star, X } from "lucide-react";
import { useApp } from "./app-context";
import { WatchCard } from "./watch-card";
import { openPanel, panelStore } from "./stores";
import { useWatchDialog } from "./watch-dialog";
import { PlainButton, Button, Spinner } from "./ui";
import { api, fetcher } from "@/lib/client";
import { relativeTime } from "@/lib/format";
import { useAirports } from "@/lib/airports-client";
import { cn } from "@/lib/utils";
import { readable } from "@/lib/watch-display";
import type { WatchRow } from "@/lib/watch-types";
import { checkNote } from "@/lib/watch-logic";

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
  const { me } = useApp();
  const { data, isLoading } = useWatches();
  const { data: alerts, mutate: mutateAlerts } = useAlerts();
  const watch = useWatchDialog();
  useAirports();

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && openPanel(null);
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

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
            <p className="text-xs text-muted">{checkNote(Boolean(me?.guest))} Tap Watch on any search to add one.</p>
          </div>
          <div className="flex items-center gap-1">
            <Button size="sm" variant="soft" onClick={() => watch.edit()}>
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
                      {readable(a.message)} <span className="text-xs text-faint">{relativeTime(a.createdAt)}</span>
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
              <div className="font-semibold">You&apos;re not watching any flights yet</div>
              <p className="mx-auto mt-1 max-w-xs text-sm text-muted">
                Tap Watch on any search and FlightScout keeps checking the price for you, so you know when to book.
              </p>
            </div>
          )}
          {data?.map((w) => (
            <WatchCard key={w.id} w={w} all={data} compact />
          ))}
        </div>
      </aside>
      {watch.element}
    </>
  );
}
