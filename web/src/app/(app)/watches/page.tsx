"use client";
import { watchHref } from "@/lib/watch-slug";
import Link from "next/link";
import useSWR from "swr";
import { ArrowDownRight, ArrowUpRight, Pause, Play, Plus, RefreshCw } from "lucide-react";
import { useState } from "react";
import { useApp } from "@/components/app-context";
import { Sparkline } from "@/components/sparkline";
import { useWatchDialog } from "@/components/watch-dialog";
import { Badge, Button, Card, Empty, PageHeader, Spinner } from "@/components/ui";
import { api, fetcher } from "@/lib/client";
import { formatDate, relativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { checkNote } from "@/lib/watch-logic";

export type WatchRow = {
  id: number;
  name: string;
  origins: string[];
  destinations: string[];
  tripType: "oneway" | "roundtrip";
  departStart: string;
  departEnd: string;
  nightsMin: number | null;
  nightsMax: number | null;
  cabin: string;
  adults: number;
  maxStops: number | null;
  currency: string;
  includeSplit: boolean;
  alertBelow: number | null;
  alertDropPct: number | null;
  active: boolean;
  lastCheckedAt: string | null;
  bestPrice: number | null;
  prevPrice: number | null;
  lowestPrice: number | null;
  bestTrip: unknown;
  notes: string | null;
  sparkline?: { day: string; price: number }[];
};

export default function WatchesPage() {
  const { data, mutate, isLoading } = useSWR<WatchRow[]>("/watches", fetcher);
  const { me } = useApp();
  const watch = useWatchDialog();
  const [checking, setChecking] = useState<number | null>(null);

  async function check(id: number) {
    setChecking(id);
    try {
      await api(`/watches/${id}/check`, { body: {} });
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setChecking(null);
      mutate();
    }
  }

  return (
    <div>
      <PageHeader
        title="Watchlist"
        sub={`Routes you watch. ${checkNote(Boolean(me?.guest))} Prices build up into history you can chart and compare.`}
        actions={
          <Button variant="primary" onClick={() => watch.open()}>
            <Plus className="size-4" /> New watch
          </Button>
        }
      />
      {isLoading && <Spinner />}
      {data && !data.length && (
        <Empty
          title="Nothing on your watchlist yet"
          action={
            <Button variant="primary" onClick={() => watch.open()}>
              <Plus className="size-4" /> Watch a route
            </Button>
          }
        >
          Watch a route with a date window and FlightScout tracks the cheapest fares daily, including split ticket routes if you want.
          You can also watch any search or result with one click.
        </Empty>
      )}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        {data?.map((w) => (
          <WatchCard key={w.id} w={w}
            all={data} checking={checking === w.id} onCheck={() => check(w.id)} onToggle={async () => {
            await api(`/watches/${w.id}`, { method: "PATCH", body: { active: !w.active } });
            mutate();
          }} />
        ))}
      </div>
      {watch.element}
    </div>
  );
}

function WatchCard({ w, all, onCheck, onToggle, checking }: { w: WatchRow; all?: WatchRow[]; onCheck: () => void; onToggle: () => void; checking: boolean }) {
  const { money } = useApp();
  const delta = w.bestPrice != null && w.prevPrice != null ? w.bestPrice - w.prevPrice : null;
  const pct = delta != null && w.prevPrice ? (delta / w.prevPrice) * 100 : null;
  return (
    <Card className={cn("flex flex-col p-3", !w.active && "opacity-60")}>
      <div className="flex items-start justify-between gap-2">
        <Link href={watchHref(w, all)} className="min-w-0">
          <div className="truncate font-medium hover:text-accent">{w.name}</div>
          <div className="font-mono text-xs text-muted">
            {w.origins.join(" ")} {w.tripType === "roundtrip" ? "⇄" : "→"} {w.destinations.join(" ")}
          </div>
        </Link>
        <div className="flex shrink-0 gap-1">
          {!w.active && <Badge>Paused</Badge>}
          {w.includeSplit && <Badge tone="info">Smart</Badge>}
        </div>
      </div>
      <div className="mt-1 text-xs text-muted">
        {formatDate(w.departStart, false)}
        {w.departEnd !== w.departStart && ` to ${formatDate(w.departEnd, false)}`}
        {w.tripType === "roundtrip" && w.nightsMin != null && ` · ${w.nightsMin}${w.nightsMax && w.nightsMax !== w.nightsMin ? `–${w.nightsMax}` : ""} nights`}
        {w.cabin !== "economy" && ` · ${w.cabin}`}
      </div>
      <div className="mt-3 flex items-end justify-between gap-3">
        <div>
          <div className="text-2xl font-semibold tabular-nums">{money(w.bestPrice, w.currency)}</div>
          <div className="flex items-center gap-2 text-xs">
            {pct != null && Math.abs(pct) >= 0.5 ? (
              <span className={cn("inline-flex items-center font-medium", delta! < 0 ? "text-good" : "text-bad")}>
                {delta! < 0 ? <ArrowDownRight className="size-3.5" /> : <ArrowUpRight className="size-3.5" />}
                {Math.abs(pct).toFixed(0)}%
              </span>
            ) : (
              w.prevPrice != null && <span className="text-muted">no change</span>
            )}
            {w.lowestPrice != null && <span className="text-muted">low {money(w.lowestPrice, w.currency)}</span>}
          </div>
        </div>
        <div className="w-32">
          <Sparkline data={(w.sparkline ?? []).map((p) => p.price)} />
        </div>
      </div>
      <div className="mt-3 flex items-center justify-between border-t border-border pt-2 text-xs text-muted">
        <span>checked {relativeTime(w.lastCheckedAt)}</span>
        <div className="flex gap-1">
          <Button size="sm" variant="ghost" onClick={onToggle} title={w.active ? "Pause" : "Resume"}>
            {w.active ? <Pause className="size-3.5" /> : <Play className="size-3.5" />}
          </Button>
          <Button size="sm" variant="ghost" onClick={onCheck} loading={checking} title="Check now">
            {!checking && <RefreshCw className="size-3.5" />} Check now
          </Button>
        </div>
      </div>
    </Card>
  );
}
