"use client";
import { useState } from "react";
import { formatDate, parseLocal } from "@/lib/format";
import { PRICE_GRADIENT, priceScale } from "@/lib/price-scale";

export type Cell = { depart: string; nights: number | null; value: number; url?: string | null; observed: string };

// Depart date (columns) by trip length (rows), colored green (cheapest) to
// red like every other price in the app. Latest known price per cell.
export function DateHeatmap({ cells, format }: { cells: Cell[]; format: (v: number) => string }) {
  const [hover, setHover] = useState<Cell | null>(null);
  if (!cells.length) return <div className="py-8 text-center text-sm text-muted">No date level prices yet.</div>;
  const departs = [...new Set(cells.map((c) => c.depart))].sort();
  const nights = [...new Set(cells.map((c) => c.nights ?? -1))].sort((a, b) => a - b);
  const min = Math.min(...cells.map((c) => c.value));
  const max = Math.max(...cells.map((c) => c.value));
  const scale = priceScale(cells.map((c) => c.value));
  const short = (v: number) => format(v).replace(/[^0-9.,]/g, "").replace(/[.,]\d{2}$/, "");
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
                  <th key={d} className="min-w-11 font-normal text-muted" title={formatDate(d)}>
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
                          className="grid h-7 min-w-11 place-items-center rounded-[3px] px-1 text-[10px] font-medium tabular-nums text-[#0b0d10] ring-offset-1 hover:ring-2 hover:ring-fg"
                          style={{ background: scale.solid(c.value) }}
                          aria-label={`${formatDate(d)} ${n === -1 ? "" : n + " nights"} ${format(c.value)}`}
                        >
                          {short(c.value)}
                        </a>
                      ) : (
                        <div className="h-7 min-w-11 rounded-[3px] bg-surface-2" />
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
          <span className="h-2.5 w-24 rounded-full" style={{ background: PRICE_GRADIENT }} />
          <span>{format(max)}</span>
        </div>
        <div className="min-h-4 text-fg">
          {hover &&
            `${formatDate(hover.depart)}${hover.nights != null ? `, ${hover.nights} nights` : ""}: ${format(hover.value)} (seen ${formatDate(hover.observed.slice(0, 10), false)})`}
        </div>
      </div>
    </div>
  );
}
