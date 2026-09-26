"use client";
import { use } from "react";
import Link from "next/link";
import useSWR from "swr";
import { ExternalLink } from "lucide-react";
import { useApp } from "@/components/app-context";
import { ResultsView } from "@/components/results-view";
import { Badge, Card, Empty, ErrorNote, PageHeader, Spinner } from "@/components/ui";
import { fetcher } from "@/lib/client";
import { formatDate } from "@/lib/format";
import type { DatePrice, Destination, PlanResult, SearchQuery, SearchResult } from "@/lib/types";

type Row = { id: number; kind: string; origin: string; summary: string | null; query: Record<string, unknown>; payload: unknown; createdAt: string };

export default function HistoryDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data, error } = useSWR<Row>(`/searches/${id}`, fetcher);
  const { money } = useApp();
  if (error)
    return /not found|404/i.test((error as Error).message) ? (
      <Empty title="This search isn't in your history" action={<Link href="/history" className="text-sm font-medium text-accent hover:underline">Back to history</Link>}>
        It may have been deleted, or it belongs to another account.
      </Empty>
    ) : (
      <ErrorNote>{(error as Error).message}</ErrorNote>
    );
  if (!data) return <Spinner />;
  const q = (data.query ?? {}) as Record<string, unknown>;
  // saved queries come from the website, the CLI and agents: origin or origins, list or text
  const list = (...vs: unknown[]) => {
    for (const v of vs) {
      if (Array.isArray(v) && v.length) return v.map(String);
      if (typeof v === "string" && v) return v.split(",");
    }
    return [] as string[];
  };
  const str = (v: unknown) => (typeof v === "string" ? v : "");
  const from = list(q.origins, q.origin, q.start);
  const to = list(q.destinations, q.destination);
  const rerun = new URLSearchParams();
  if ((data.kind === "search" || data.kind === "plan") && from.length && to.length) {
    const dep = str(q.departure) || str(q.depart_start);
    const ret = str(q.return_date) || str(q.return_start);
    rerun.set("from", from.join(","));
    rerun.set("to", to.join(","));
    if (dep) rerun.set("d", dep);
    if (ret) rerun.set("r", ret);
    rerun.set("tt", ret ? "roundtrip" : "oneway");
    if (typeof q.adults === "number") rerun.set("adults", String(q.adults));
    if (typeof q.cabin === "string") rerun.set("cabin", q.cabin);
    if (data.kind === "plan") rerun.set("smart", "1");
  }
  const payload = (data.payload ?? null) as Record<string, unknown> | null;
  const trips = Array.isArray(payload?.trips) ? (payload!.trips as SearchResult["trips"]) : null;
  const items = (Array.isArray(payload?.items) ? payload!.items : Array.isArray(payload?.destinations) ? payload!.destinations : []) as (Destination & DatePrice)[];

  return (
    <div>
      <PageHeader
        title={data.summary ?? data.kind}
        sub={
          <span className="flex items-center gap-2">
            <Badge>{data.kind}</Badge> <Badge tone="accent">{data.origin}</Badge> {new Date(data.createdAt).toLocaleString()}
          </span>
        }
        actions={
          rerun.get("from") && (
            <Link href={`/?${rerun}`} className="inline-flex h-9 items-center rounded-md bg-accent px-3 text-sm font-medium text-accent-fg">
              Search again with live prices
            </Link>
          )
        }
      />
      <p className="mb-3 text-xs text-muted">Prices below are as they were when this search ran. Fares change, so check the live link before booking.</p>
      {!payload ? (
        <Empty title="Result payload was trimmed">Old results keep only the query. Search again for live prices.</Empty>
      ) : trips ? (
        // searches, smart routes, the trip builder and multi city trips all keep trips
        <ResultsView
          trips={trips}
          query={data.kind === "search" ? (q as unknown as SearchQuery) : { origins: from, destinations: to }}
          errors={(payload.errors as Record<string, string>) ?? {}}
          googleUrl={typeof payload.google_url === "string" ? payload.google_url : null}
          plan={data.kind !== "search" ? (payload as unknown as PlanResult) : null}
        />
      ) : !items.length ? (
        <Empty title="Nothing was found in this search" />
      ) : (
        <Card className="divide-y divide-border">
          {items.map((d, i) => (
            <div key={i} className="flex items-center gap-3 px-3 py-2 text-sm">
              <span className="font-mono">{d.origin} → {d.destination}</span>
              {"city" in d && d.city && <span className="text-muted">{d.city}</span>}
              <span className="text-muted">{formatDate(d.departure)}{d.return_date && ` to ${formatDate(d.return_date)}`}</span>
              <span className="ml-auto font-medium tabular-nums">{money(d.price, d.currency)}</span>
              {d.booking_url && (
                <a href={d.booking_url} target="_blank" rel="noopener noreferrer" className="text-accent">
                  <ExternalLink className="size-3.5" />
                </a>
              )}
            </div>
          ))}
        </Card>
      )}
    </div>
  );
}
