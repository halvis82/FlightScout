"use client";
import Link from "next/link";
import useSWRInfinite from "swr/infinite";
import { Compass, Search, Sparkles, CalendarDays, Trash2 } from "lucide-react";
import { Badge, Button, Empty, PageHeader, Spinner } from "@/components/ui";
import { api, fetcher } from "@/lib/client";
import { relativeTime } from "@/lib/format";

type Row = { id: number; kind: "search" | "plan" | "explore" | "dates"; origin: "web" | "cli" | "mcp" | "tracker"; summary: string | null; created_at: string };

const ICON = { search: Search, plan: Sparkles, explore: Compass, dates: CalendarDays };
const ORIGIN_TONE = { web: "neutral", cli: "accent", mcp: "info", tracker: "good" } as const;

export default function HistoryPage() {
  const { data, size, setSize, isLoading, mutate } = useSWRInfinite<Row[]>(
    (i, prev: Row[] | null) => (prev && !prev.length ? null : i === 0 ? "/searches?limit=50" : `/searches?limit=50&before=${prev!.at(-1)!.id}`),
    fetcher,
  );
  const rows = data?.flat() ?? [];
  const more = data && data.at(-1)?.length === 50;
  return (
    <div>
      <PageHeader title="History" sub="Every search, smart route and explore run, including ones sent by the CLI, MCP agents and watch checks." />
      {isLoading && <Spinner />}
      {!isLoading && !rows.length && <Empty title="No searches yet">Searches you run here, or push with the flightscout CLI, show up here.</Empty>}
      <div className="divide-y divide-border overflow-hidden rounded-lg border border-border bg-surface">
        {rows.map((r) => {
          const Icon = ICON[r.kind] ?? Search;
          return (
            <div key={r.id} className="flex items-center gap-3 px-3 py-2 hover:bg-surface-2">
              <Icon className="size-4 shrink-0 text-muted" />
              <Link href={`/history/${r.id}`} className="min-w-0 flex-1 truncate text-sm">
                {r.summary ?? r.kind}
              </Link>
              <Badge tone={ORIGIN_TONE[r.origin]}>{r.origin}</Badge>
              <span className="w-16 shrink-0 text-right text-xs text-faint">{relativeTime(r.created_at)}</span>
              <button
                className="rounded p-1 text-faint hover:text-bad"
                aria-label="Delete"
                onClick={async () => {
                  await api(`/searches/${r.id}`, { method: "DELETE" });
                  mutate();
                }}
              >
                <Trash2 className="size-3.5" />
              </button>
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
