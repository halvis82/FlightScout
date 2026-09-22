"use client";
import { useState } from "react";
import { formatDate, parseLocal } from "@/lib/format";

export type Cell = { depart: string; nights: number | null; value: number; url?: string | null; observed: string };

const STEPS = ["var(--seq-7)", "var(--seq-6)", "var(--seq-5)", "var(--seq-4)", "var(--seq-3)", "var(--seq-2)", "var(--seq-1)"];

// Depart date (columns) by trip length (rows). Darker means cheaper. Latest
// known price per cell.
export function DateHeatmap({ cells, format }: { cells: Cell[]; format: (v: number) => string }) {
  const [hover, setHover] = useState<Cell | null>(null);
  if (!cells.length) return <div className="py-8 text-center text-sm text-muted">No date level prices yet.</div>;
  const departs = [...new Set(cells.map((c) => c.depart))].sort();
  const nights = [...new Set(cells.map((c) => c.nights ?? -1))].sort((a, b) => a - b);
  const min = Math.min(...cells.map((c) => c.value));
  const max = Math.max(...cells.map((c) => c.value));
  const idx = (v: number) => (max === min ? 0 : Math.min(STEPS.length - 1, Math.floor(((v - min) / (max - min)) * STEPS.length)));
  const map = new Map(cells.map((c) => [`${c.depart}|${c.nights ?? -1}`, c]));
  return (
    <div>
      <div className="overflow-x-auto">
        <table className="border-separate border-spacing-[2px] text-[11px]">
          <thead>
            <tr>
              <th className="pr-2 text-left font-normal text-faint">{nights[0] === -1 ? "" : "Nights"}</th>
              {departs.map((d) => {
                const { da } = parseLocal(d);
                return (
                  <th key={d} className="w-8 min-w-8 font-normal text-muted" title={formatDate(d)}>
                    {da === 1 || d === departs[0] ? formatDate(d, false) : da}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {nights.map((n) => (
              <tr key={n}>
                <td className="pr-2 text-right text-muted">{n === -1 ? "One way" : n}</td>
                {departs.map((d) => {
                  const c = map.get(`${d}|${n}`);
                  return (
                    <td key={d} className="p-0">
                      {c ? (
                        <a
                          href={c.url ?? undefined}
                          target="_blank"
                          rel="noopener noreferrer"
                          onMouseEnter={() => setHover(c)}
                          onMouseLeave={() => setHover(null)}
                          className="block h-7 w-8 rounded-[3px] ring-offset-1 hover:ring-2 hover:ring-fg"
                          style={{ background: STEPS[idx(c.value)] }}
                          aria-label={`${formatDate(d)} ${n === -1 ? "" : n + " nights"} ${format(c.value)}`}
                        />
                      ) : (
                        <div className="h-7 w-8 rounded-[3px] bg-surface-2" />
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
        <div className="flex items-center gap-1.5">
          <span>{format(min)}</span>
          <div className="flex">
            {STEPS.map((s) => (
              <span key={s} className="h-2.5 w-5" style={{ background: s }} />
            ))}
          </div>
          <span>{format(max)}</span>
          <span className="text-faint">darker is cheaper</span>
        </div>
        <div className="min-h-4 text-fg">
          {hover &&
            `${formatDate(hover.depart)}${hover.nights != null ? `, ${hover.nights} nights` : ""}: ${format(hover.value)} (seen ${formatDate(hover.observed.slice(0, 10), false)})`}
        </div>
      </div>
    </div>
  );
}
