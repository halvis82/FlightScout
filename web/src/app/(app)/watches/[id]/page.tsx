"use client";
import { use, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { ExternalLink, Pause, Pencil, Play, RefreshCw, Search, Trash2 } from "lucide-react";
import { useApp } from "@/components/app-context";
import { DateHeatmap, type Cell } from "@/components/date-heatmap";
import { PriceChart, type SeriesPoint } from "@/components/price-chart";
import { TripCard } from "@/components/trip-card";
import { WatchDialog, type WatchForm } from "@/components/watch-dialog";
import { Badge, Button, Card, Empty, ErrorNote, PageHeader, Segmented, Spinner } from "@/components/ui";
import { api, fetcher } from "@/lib/client";
import { dayDiff, formatDate, formatDuration, relativeTime } from "@/lib/format";
import type { Trip } from "@/lib/types";
import type { WatchRow } from "@/lib/watch-types";

type Obs = {
  id: number;
  observed_at: string;
  depart_date: string;
  return_date: string | null;
  price: number;
  currency: string;
  value: number;
  source: string;
  kind: string;
  route: string | null;
  duration_min: number | null;
  booking_url: string | null;
};

const KIND = (k: string) => (k === "single" ? "One ticket" : "Smart route");
const SOURCE = (s: string) => (s === "google" ? "Google Flights" : s === "kiwi" ? "Kiwi.com" : s.includes("+") ? "Mixed" : s);

export default function WatchDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const { money, convert, currency } = useApp();
  const { data, mutate, error } = useSWR<{ watch: WatchRow; observations: Obs[] }>(`/watches/${id}/history`, fetcher);
  const [by, setBy] = useState<"best" | "kind" | "source">("best");
  const [editing, setEditing] = useState(false);
  const [checking, setChecking] = useState(false);
  const [checkErr, setCheckErr] = useState<string | null>(null);

  const w = data?.watch;
  const obs = useMemo(() => data?.observations ?? [], [data]);

  const { chart, series } = useMemo(() => {
    const key = (o: Obs) => (by === "best" ? "Cheapest found" : by === "kind" ? KIND(o.kind) : SOURCE(o.source));
    const days = new Map<string, Record<string, number>>();
    const count = new Map<string, number>();
    for (const o of obs) {
      const d = o.observed_at.slice(0, 10);
      const k = key(o);
      count.set(k, (count.get(k) ?? 0) + 1);
      const row = days.get(d) ?? {};
      row[k] = Math.min(row[k] ?? Infinity, o.value);
      days.set(d, row);
    }
    // three most common series keep their own line, the rest fold to "Other"
    const top = [...count.entries()].sort((a, b) => b[1] - a[1]).map((x) => x[0]);
    const keep = top.length > 3 ? top.slice(0, 2) : top;
    const series = top.length > 3 ? [...keep, "Other"] : keep;
    const chart: SeriesPoint[] = [...days.entries()]
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([day, row]) => {
        const out: SeriesPoint = { day };
        for (const [k, v] of Object.entries(row)) {
          const s = keep.includes(k) ? k : "Other";
          out[s] = Math.min((out[s] as number) ?? Infinity, Math.round(v));
        }
        return out;
      });
    return { chart, series };
  }, [obs, by]);

  const cells = useMemo<Cell[]>(() => {
    const latest = new Map<string, Obs>();
    for (const o of obs) {
      const nights = o.return_date ? dayDiff(o.depart_date, o.return_date) : null;
      const k = `${o.depart_date}|${nights}`;
      const cur = latest.get(k);
      // newest check wins, cheapest within the same day
      if (!cur || o.observed_at.slice(0, 10) > cur.observed_at.slice(0, 10) || (o.observed_at.slice(0, 10) === cur.observed_at.slice(0, 10) && o.value < cur.value))
        latest.set(k, o);
    }
    return [...latest.values()].map((o) => ({
      depart: o.depart_date,
      nights: o.return_date ? dayDiff(o.depart_date, o.return_date) : null,
      value: o.value,
      url: o.booking_url,
      observed: o.observed_at,
    }));
  }, [obs]);

  if (error) return <ErrorNote>{(error as Error).message}</ErrorNote>;
  if (!w) return <Spinner />;

  const delta = w.bestPrice != null && w.prevPrice != null ? w.bestPrice - w.prevPrice : null;
  const checks = new Set(obs.map((o) => o.observed_at.slice(0, 16))).size;
  const searchParams = new URLSearchParams({
    from: w.origins.join(","),
    to: w.destinations.join(","),
    d: w.departStart,
    tt: w.tripType,
    cur: w.currency,
    cabin: w.cabin,
    adults: String(w.adults),
    flex: String(Math.min(7, Math.ceil(dayDiff(w.departStart, w.departEnd) / 2))),
  });
  if (w.tripType === "roundtrip") {
    const mid = Math.floor(dayDiff(w.departStart, w.departEnd) / 2);
    const dep = new Date(w.departStart + "T00:00:00Z");
    dep.setUTCDate(dep.getUTCDate() + mid);
    searchParams.set("d", dep.toISOString().slice(0, 10));
    const ret = new Date(dep);
    ret.setUTCDate(ret.getUTCDate() + (w.nightsMin ?? 7));
    searchParams.set("r", ret.toISOString().slice(0, 10));
  }
  if (w.includeSplit) searchParams.set("smart", "1");
  if (w.tripType === "multicity" && Array.isArray(w.legs)) {
    // back to the multi city form: each leg's destination, date and flexibility
    searchParams.set("to", "");
    searchParams.set(
      "ml",
      JSON.stringify(
        (w.legs as { destinations: string[]; date: string; after?: number; arrive_by?: string | null }[]).map((l) => ({
          to: l.destinations,
          date: l.date,
          flex: l.arrive_by ? "by" : (l.after ?? 0),
        })),
      ),
    );
  }

  const form: WatchForm = {
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
    notes: w.notes,
  };

  async function check() {
    setChecking(true);
    setCheckErr(null);
    try {
      await api(`/watches/${id}/check`, { body: {} });
      mutate();
    } catch (e) {
      setCheckErr((e as Error).message);
    } finally {
      setChecking(false);
    }
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title={w.name}
        sub={
          <span className="font-mono">
            {w.origins.join(" ")} {w.tripType === "roundtrip" ? "⇄" : "→"} {w.destinations.join(" ")}
            <span className="ml-2 font-sans">
              {formatDate(w.departStart, false)}
              {w.departEnd !== w.departStart && ` to ${formatDate(w.departEnd, false)}`}
              {w.tripType === "roundtrip" && w.nightsMin != null && ` · ${w.nightsMin}${w.nightsMax && w.nightsMax !== w.nightsMin ? `–${w.nightsMax}` : ""} nights`}
              {` · ${w.cabin} · ${w.adults} adult${w.adults > 1 ? "s" : ""}`}
            </span>
          </span>
        }
        actions={
          <>
            <Link href={`/?${searchParams}`} className="inline-flex h-9 items-center gap-1.5 rounded-md border border-border bg-surface px-3 text-sm font-medium hover:bg-surface-2">
              <Search className="size-4" /> Search now
            </Link>
            <Button onClick={check} loading={checking}>
              {!checking && <RefreshCw className="size-4" />} Check now
            </Button>
            <Button onClick={() => setEditing(true)}>
              <Pencil className="size-4" /> Edit
            </Button>
            <Button
              onClick={async () => {
                await api(`/watches/${id}`, { method: "PATCH", body: { active: !w.active } });
                mutate();
              }}
            >
              {w.active ? <Pause className="size-4" /> : <Play className="size-4" />} {w.active ? "Pause" : "Resume"}
            </Button>
            <Button
              variant="danger"
              onClick={async () => {
                if (!confirm(`Delete "${w.name}" and its price history?`)) return;
                await api(`/watches/${id}`, { method: "DELETE" });
                router.push("/watches");
              }}
            >
              <Trash2 className="size-4" />
            </Button>
          </>
        }
      />
      {checkErr && <ErrorNote>{checkErr}</ErrorNote>}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label="Current best" value={money(w.bestPrice, w.currency)} sub={w.currency !== currency ? `${w.bestPrice?.toFixed(0) ?? "–"} ${w.currency}` : undefined} />
        <Stat
          label="Since last check"
          value={delta == null ? "–" : `${delta > 0 ? "+" : delta < 0 ? "−" : ""}${money(Math.abs(delta), w.currency)}`}
          tone={delta == null || delta === 0 ? undefined : delta < 0 ? "good" : "bad"}
        />
        <Stat label="All time low" value={money(w.lowestPrice, w.currency)} />
        <Stat label="Target" value={w.alertBelow != null ? money(w.alertBelow, w.currency) : w.alertDropPct != null ? `${w.alertDropPct}% drop` : "None"} />
        <Stat label="Checks" value={String(checks)} sub={`last ${relativeTime(w.lastCheckedAt)}`} />
      </div>

      <Card className="p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="font-semibold">Price over time</h2>
            <p className="text-xs text-muted">Lowest price seen each day across every date in the window, in {w.currency}{w.currency !== currency && `, shown in ${currency}`}.</p>
          </div>
          <Segmented
            size="sm"
            value={by}
            onChange={setBy}
            options={[
              { value: "best", label: "Cheapest" },
              { value: "kind", label: "By ticket type" },
              { value: "source", label: "By source" },
            ]}
          />
        </div>
        {chart.length ? (
          <PriceChart data={chart} series={series} format={(v) => money(v, w.currency, { compact: v >= 100000 })} />
        ) : (
          <Empty title="No price history yet">Run a check now, or wait for the daily tracker.</Empty>
        )}
      </Card>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Card className="p-4">
          <h2 className="font-semibold">Prices by date</h2>
          <p className="mb-3 text-xs text-muted">Latest known price for each departure date{w.tripType === "roundtrip" && " and trip length"}. Click a cell to open the fare.</p>
          <DateHeatmap cells={cells} format={(v) => money(v, w.currency)} />
        </Card>
        <div className="space-y-2">
          <h2 className="font-semibold">Best option found</h2>
          {w.bestTrip ? (
            <TripCard trip={w.bestTrip as Trip} />
          ) : (
            <Empty title="Nothing found yet" />
          )}
          {w.notes && <p className="text-sm text-muted">{w.notes}</p>}
        </div>
      </div>

      <Card className="overflow-hidden">
        <div className="border-b border-border px-4 py-3">
          <h2 className="font-semibold">Observations</h2>
          <p className="text-xs text-muted">Every price recorded for this watch, newest first.</p>
        </div>
        <div className="max-h-[480px] overflow-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-surface-2 text-left text-xs text-muted">
              <tr>
                <th className="px-4 py-2 font-medium">Seen</th>
                <th className="px-2 py-2 font-medium">Depart</th>
                <th className="px-2 py-2 font-medium">Return</th>
                <th className="px-2 py-2 font-medium">Route</th>
                <th className="hidden px-2 py-2 font-medium md:table-cell">Duration</th>
                <th className="px-2 py-2 font-medium">Source</th>
                <th className="px-2 py-2 text-right font-medium">Price</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody>
              {[...obs].reverse().slice(0, 500).map((o) => (
                <tr key={o.id} className="border-t border-border">
                  <td className="px-4 py-1.5 text-muted">{relativeTime(o.observed_at)}</td>
                  <td className="px-2 py-1.5">{formatDate(o.depart_date, false)}</td>
                  <td className="px-2 py-1.5">{o.return_date ? formatDate(o.return_date, false) : "–"}</td>
                  <td className="px-2 py-1.5 font-mono text-xs">{o.route}</td>
                  <td className="hidden px-2 py-1.5 text-muted md:table-cell">{formatDuration(o.duration_min)}</td>
                  <td className="px-2 py-1.5">
                    <Badge tone={o.kind === "single" ? "neutral" : "info"}>{SOURCE(o.source)}{o.kind !== "single" && ` · ${o.kind}`}</Badge>
                  </td>
                  <td className="px-2 py-1.5 text-right font-medium tabular-nums" title={`${o.price} ${o.currency}`}>
                    {money(convert(o.price, o.currency, w.currency), w.currency)}
                  </td>
                  <td className="px-4 py-1.5 text-right">
                    {o.booking_url && (
                      <a href={o.booking_url} target="_blank" rel="noopener noreferrer" className="text-accent" aria-label="Open fare">
                        <ExternalLink className="inline size-3.5" />
                      </a>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <WatchDialog open={editing} onClose={() => setEditing(false)} initial={form} watchId={w.id} onSaved={() => mutate()} />
    </div>
  );
}

function Stat({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "good" | "bad" }) {
  return (
    <Card className="px-3 py-2.5">
      <div className="text-[11px] font-medium uppercase tracking-wide text-muted">{label}</div>
      <div className={`mt-0.5 text-lg font-semibold tabular-nums ${tone === "good" ? "text-good" : tone === "bad" ? "text-bad" : ""}`}>{value}</div>
      {sub && <div className="text-xs text-faint">{sub}</div>}
    </Card>
  );
}
