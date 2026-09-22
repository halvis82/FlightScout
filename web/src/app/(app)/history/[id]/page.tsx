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
  if (error) return <ErrorNote>{(error as Error).message}</ErrorNote>;
  if (!data) return <Spinner />;
  const q = data.query as Record<string, unknown>;
  const rerun = new URLSearchParams();
  if (data.kind === "search") {
    const s = q as unknown as SearchQuery;
    rerun.set("from", s.origins.join(","));
    rerun.set("to", s.destinations.join(","));
    rerun.set("d", s.departure);
    if (s.return_date) rerun.set("r", s.return_date);
    rerun.set("tt", s.return_date ? "roundtrip" : "oneway");
    if (s.currency) rerun.set("cur", s.currency);
  } else if (data.kind === "plan") {
    rerun.set("from", (q.origins as string[]).join(","));
    rerun.set("to", (q.destinations as string[]).join(","));
    rerun.set("d", q.depart_start as string);
    if (q.return_start) rerun.set("r", q.return_start as string);
    rerun.set("smart", "1");
  }

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
      {!data.payload ? (
        <Empty title="Result payload was trimmed">Old results keep only the query. Search again for live prices.</Empty>
      ) : data.kind === "search" || data.kind === "plan" ? (
        <ResultsView
          trips={(data.payload as SearchResult | PlanResult).trips ?? []}
          query={data.kind === "search" ? (q as unknown as SearchQuery) : { origins: q.origins as string[], destinations: q.destinations as string[] }}
          errors={(data.payload as SearchResult).errors}
          googleUrl={(data.payload as SearchResult).google_url}
          plan={data.kind === "plan" ? (data.payload as PlanResult) : null}
        />
      ) : (
        <Card className="divide-y divide-border">
          {(((data.payload as { items?: (Destination | DatePrice)[] }).items ?? []) as (Destination & DatePrice)[]).map((d, i) => (
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
