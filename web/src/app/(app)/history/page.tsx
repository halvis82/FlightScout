"use client";
import Link from "next/link";
import useSWRInfinite from "swr/infinite";
import { Compass, Search, Sparkles, CalendarDays, Trash2 } from "lucide-react";
import { PlainButton, Badge, Button, Empty, PageHeader, Spinner } from "@/components/ui";
import { api, fetcher } from "@/lib/client";
import { relativeTime } from "@/lib/format";
import { useAirports } from "@/lib/airports-client";
import { readableSummary } from "@/lib/watch-display";

type Row = { id: number; kind: "search" | "plan" | "explore" | "dates" | "multicity"; origin: "web" | "local" | "cli" | "mcp" | "tracker"; summary: string | null; created_at: string };

const ICON = { search: Search, plan: Sparkles, explore: Compass, dates: CalendarDays, multicity: Search };
const KIND = { search: "Search", plan: "Smart routes", explore: "Explore", dates: "Date prices", multicity: "Multi city" };
// searches from the website need no label; the others say where they came from
const ORIGIN = { cli: ["Command line", "accent"], mcp: ["AI assistant", "info"], tracker: ["Price check", "good"] } as const;

export default function HistoryPage() {
  const { data, size, setSize, isLoading, mutate } = useSWRInfinite<Row[]>(
    (i, prev: Row[] | null) => (prev && !prev.length ? null : i === 0 ? "/searches?limit=50" : `/searches?limit=50&before=${prev!.at(-1)!.id}`),
    fetcher,
  );
  useAirports(); // city names in the summaries
  const rows = data?.flat() ?? [];
  const more = data && data.at(-1)?.length === 50;
  return (
    <div>
      <PageHeader title="History" sub="Your recent searches, so you can open any of them again with one click." />
      {isLoading && <Spinner />}
      {!isLoading && !rows.length && <Empty title="No searches yet">Searches you make show up here.</Empty>}
      <div className="divide-y divide-border overflow-hidden rounded-lg border border-border bg-surface">
        {rows.map((r) => {
          const Icon = ICON[r.kind] ?? Search;
          return (
            <div key={r.id} className="flex items-center gap-3 px-3 py-2 hover:bg-surface-2">
              <span title={KIND[r.kind] ?? r.kind}>
                <Icon className="size-4 shrink-0 text-muted" />
              </span>
              <Link href={`/history/${r.id}`} className="min-w-0 flex-1 truncate text-sm" title={r.summary ?? undefined}>
                {r.summary ? readableSummary(r.summary.replace(/^Smart routes /, "")) : KIND[r.kind] ?? r.kind}
                {r.kind !== "search" && <span className="text-muted"> · {KIND[r.kind] ?? r.kind}</span>}
              </Link>
              {r.origin in ORIGIN && <Badge tone={ORIGIN[r.origin as keyof typeof ORIGIN][1]}>{ORIGIN[r.origin as keyof typeof ORIGIN][0]}</Badge>}
              <span className="w-16 shrink-0 text-right text-xs text-faint">{relativeTime(r.created_at)}</span>
              <PlainButton
                className="rounded p-1 text-faint hover:text-bad"
                aria-label="Delete from history"
                onClick={async () => {
                  await api(`/searches/${r.id}`, { method: "DELETE" });
                  mutate();
                }}
              >
                <Trash2 className="size-3.5" />
              </PlainButton>
            </div>
          );
        })}
      </div>
      {more && (
        <div className="mt-3 flex justify-center">
          <Button onClick={() => setSize(size + 1)}>Load more</Button>
        </div>
      )}
    </div>
  );
}
