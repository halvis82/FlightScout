"use client";
import Link from "next/link";
import { useRef, useState } from "react";
import { mutate as globalMutate } from "swr";
import { ArrowDownRight, ArrowUpRight, Bell, BellOff, MoreHorizontal, Pause, Pencil, Play, RefreshCw, Trash2 } from "lucide-react";
import { useApp } from "./app-context";
import { Dialog } from "./dialog";
import { Sparkline } from "./sparkline";
import { openPanel } from "./stores";
import { WatchDialog, watchToForm } from "./watch-dialog";
import { Badge, Button, Spinner, Switch, useDismiss } from "./ui";
import { api } from "@/lib/client";
import { relativeTime } from "@/lib/format";
import { useAirports } from "@/lib/airports-client";
import { cn } from "@/lib/utils";
import { airportsLine, alertRule, tripLine, watchTitle } from "@/lib/watch-display";
import { watchHref } from "@/lib/watch-slug";
import type { WatchRow } from "@/lib/watch-types";

const refresh = () => {
  globalMutate("/watches");
  globalMutate("/alerts");
};

// One watched trip: where and when in words, its price and trend, its alert,
// and everything you can do with it. `compact` is the side panel version.
export function WatchCard({ w, all, compact }: { w: WatchRow; all?: WatchRow[]; compact?: boolean }) {
  useAirports();
  const { money, me, settings } = useApp();
  const [checking, setChecking] = useState(false);
  const [editing, setEditing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const href = watchHref(w, all);
  const title = watchTitle(w);
  const delta = w.bestPrice != null && w.prevPrice != null ? w.bestPrice - w.prevPrice : null;
  const pct = delta != null && w.prevPrice ? (delta / w.prevPrice) * 100 : null;
  const rule = alertRule(w, money);
  const close = compact ? () => openPanel(null) : undefined;

  async function act(fn: () => Promise<unknown>) {
    setErr(null);
    try {
      await fn();
    } catch (e) {
      setErr((e as Error).message);
    }
    refresh();
  }
  const check = () => {
    setChecking(true);
    act(() => api(`/watches/${w.id}/check`, { body: {} })).finally(() => setChecking(false));
  };

  return (
    <div className={cn("flex flex-col rounded-2xl border border-border bg-surface shadow-[var(--shadow)] transition-colors hover:border-border-strong", compact ? "p-3" : "p-4", !w.active && "opacity-70")}>
      <Link href={href} onClick={close} className="group block">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className={cn("font-semibold group-hover:text-accent", compact ? "text-base" : "text-lg leading-snug")}>{title}</div>
            <div className="mt-0.5 text-sm text-muted">{tripLine(w)}</div>
            <div className="mt-0.5 truncate font-mono text-[11px] text-faint" title="Airports">
              {airportsLine(w)}
            </div>
          </div>
          <div className="shrink-0 text-right">
            <div className={cn("font-bold tabular-nums", compact ? "text-xl" : "text-2xl")}>{w.bestPrice != null ? money(w.bestPrice, w.currency) : "–"}</div>
            {pct != null && Math.abs(pct) >= 0.5 ? (
              <div className={cn("inline-flex items-center gap-0.5 text-xs font-medium", delta! < 0 ? "text-good" : "text-bad")}>
                {delta! < 0 ? <ArrowDownRight className="size-3.5" /> : <ArrowUpRight className="size-3.5" />}
                {delta! < 0 ? "Down" : "Up"} {Math.abs(pct).toFixed(0)}%
              </div>
            ) : (
              <div className="text-xs text-muted">{w.bestPrice == null ? "Not checked yet" : w.prevPrice != null ? "No change" : "First price"}</div>
            )}
            {w.lowestPrice != null && <div className="text-xs text-muted">Lowest {money(w.lowestPrice, w.currency)}</div>}
          </div>
        </div>
        {(w.sparkline?.length ?? 0) > 1 && (
          <div className="mt-3 h-10">
            <Sparkline data={(w.sparkline ?? []).map((p) => p.price)} className="h-10 w-full" />
          </div>
        )}
      </Link>

      <div className="mt-3 flex items-center justify-between gap-3 rounded-xl bg-surface-2 px-3 py-2 text-sm">
        <div className="flex min-w-0 items-start gap-2">
          {rule ? <Bell className="mt-0.5 size-4 shrink-0 text-accent" /> : <BellOff className="mt-0.5 size-4 shrink-0 text-faint" />}
          <span className="min-w-0">
            {rule ? (
              <>
                Alert when <span className="font-medium">{rule}</span>
              </>
            ) : (
              <span className="text-muted">No price alert</span>
            )}
          </span>
        </div>
        {rule && me?.user && me.features.email ? (
          settings?.emailAlerts ? (
            <Switch
              checked={w.emailAlerts !== false}
              onChange={(on) => act(() => api(`/watches/${w.id}`, { method: "PATCH", body: { email_alerts: on } }))}
              label={<span className="text-xs text-muted">Email</span>}
            />
          ) : (
            <Link href="/settings" onClick={close} className="shrink-0 text-xs text-accent hover:underline">
              Turn on email
            </Link>
          )
        ) : (
          !rule && (
            <button onClick={() => setEditing(true)} className="shrink-0 text-xs font-medium text-accent hover:underline">
              Set one
            </button>
          )
        )}
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
        <span className="flex min-w-0 flex-wrap items-center gap-1.5">
          {w.active ? <span>Checked {relativeTime(w.lastCheckedAt)}</span> : <Badge tone="warn">Paused</Badge>}
          {w.includeSplit && <Badge tone="info" title="Also tracks split tickets and stopovers">Smart routes</Badge>}
        </span>
        <div className="flex shrink-0 items-center gap-1">
          <Button size="sm" variant="soft" onClick={check} disabled={checking}>
            {checking ? <Spinner className="size-3.5" /> : <RefreshCw className="size-3.5" />} Check now
          </Button>
          <Menu
            items={[
              { label: "Edit", icon: Pencil, onClick: () => setEditing(true) },
              {
                label: w.active ? "Pause checking" : "Resume checking",
                icon: w.active ? Pause : Play,
                onClick: () => act(() => api(`/watches/${w.id}`, { method: "PATCH", body: { active: !w.active } })),
              },
              { label: "Delete", icon: Trash2, danger: true, onClick: () => setDeleting(true) },
            ]}
          />
        </div>
      </div>
      {err && <p className="mt-2 text-xs text-bad">{err}</p>}

      <WatchDialog open={editing} onClose={() => setEditing(false)} initial={watchToForm(w)} watchId={w.id} onSaved={refresh} />
      <DeleteWatch open={deleting} onClose={() => setDeleting(false)} w={w} title={title} />
    </div>
  );
}

export function DeleteWatch({ open, onClose, w, title, onDeleted }: { open: boolean; onClose: () => void; w: WatchRow; title: string; onDeleted?: () => void }) {
  const [busy, setBusy] = useState(false);
  return (
    <Dialog open={open} onClose={onClose} title="Delete this watch?">
      <p className="text-sm">
        <span className="font-medium">{title}</span> and its price history will be removed. This can&apos;t be undone.
      </p>
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button
          variant="danger"
          loading={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await api(`/watches/${w.id}`, { method: "DELETE" });
              onClose();
              onDeleted?.();
              refresh();
            } finally {
              setBusy(false);
            }
          }}
        >
          <Trash2 className="size-4" /> Delete
        </Button>
      </div>
    </Dialog>
  );
}

type Item = { label: string; icon: React.ComponentType<{ className?: string }>; onClick: () => void; danger?: boolean };

function Menu({ items }: { items: Item[] }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useDismiss(ref, open, () => setOpen(false));
  return (
    <div ref={ref} className="relative">
      <Button size="sm" variant="ghost" aria-label="More actions" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <MoreHorizontal className="size-4" />
      </Button>
      {open && (
        <div role="menu" className="absolute right-0 bottom-full z-20 mb-1 w-44 overflow-hidden rounded-xl border border-border bg-surface py-1 shadow-[var(--shadow-lg)]">
          {items.map(({ label, icon: Icon, onClick, danger }) => (
            <button
              key={label}
              role="menuitem"
              onClick={() => {
                setOpen(false);
                onClick();
              }}
              className={cn("flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-surface-2", danger && "text-bad")}
            >
              <Icon className="size-4" /> {label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
