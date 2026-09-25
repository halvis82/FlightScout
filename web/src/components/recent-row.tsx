"use client";
import Link from "next/link";
import { History, X } from "lucide-react";
import { removeRecent, useRecent, type Recent } from "@/lib/recent";
import { cityOf } from "@/lib/airports-client";
import { formatDate } from "@/lib/format";

const place = (codes: string[]) => (codes.length === 1 ? (cityOf(codes[0]) ?? codes[0]) : codes.join("/"));

// Recent searches as a scrollable row of one click repeats, plus the full
// history (website, CLI and agents) one click away.
export function RecentRow({ onPick }: { onPick: (r: Recent) => void }) {
  const recent = useRecent();
  if (!recent.length) return null;
  return (
    <div className="flex items-center gap-2">
      <History className="size-3.5 shrink-0 text-faint" aria-hidden />
      <div className="flex min-w-0 flex-1 gap-1.5 overflow-x-auto pb-1 [scrollbar-width:thin]">
        {recent.map((r, i) => (
          <span key={r.at} className="group inline-flex shrink-0 items-center rounded-full border border-border bg-surface text-xs">
            <button
              type="button"
              onClick={() => onPick(r)}
              className="py-1 pl-2.5 pr-1 text-muted hover:text-fg"
              title={`${r.from.join(",")} to ${r.to.join(",")}`}
            >
              {place(r.from)} → {place(r.to)} <span className="text-faint">{formatDate(r.depart, false)}</span>
            </button>
            <button
              type="button"
              aria-label="Remove from recent"
              onClick={() => removeRecent(i)}
              className="mr-1 rounded-full p-0.5 text-faint opacity-0 hover:text-fg group-hover:opacity-100"
            >
              <X className="size-3" />
            </button>
          </span>
        ))}
      </div>
      <Link href="/history" className="shrink-0 text-xs text-faint hover:text-fg">
        All history
      </Link>
    </div>
  );
}
