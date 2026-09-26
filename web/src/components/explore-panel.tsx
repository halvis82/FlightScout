"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { ExternalLink, Info } from "lucide-react";
import { useApp } from "./app-context";
import { StarButton } from "./favorites";
import { RouteMap, type MapPoint } from "./route-map";
import { Segmented, Spinner } from "./ui";
import { api } from "@/lib/client";
import { airport, expandCodes } from "@/lib/airports-client";
import { addDays, dayDiff, formatDate } from "@/lib/format";
import { priceScale } from "@/lib/price-scale";
import type { Destination } from "@/lib/types";
import { cn } from "@/lib/utils";

type Sort = "price" | "date";

// Shown on the search page while no destination is picked: the cheapest places
// to go from the chosen origins around the chosen dates. Updates by itself
// (debounced) and fills in over three engine batches: broad first, then depth.
export function ExplorePanel({
  origins,
  depart,
  ret,
  roundTrip,
  flex,
  retFlex = 0,
  onPick,
}: {
  origins: string[];
  depart: string;
  ret: string;
  roundTrip: boolean;
  flex: number;
  retFlex?: number;
  onPick: (d: Destination) => void;
}) {
  const { currency, money, convert } = useApp();
  const [items, setItems] = useState<Map<string, Destination>>(new Map());
  const [loading, setLoading] = useState(0); // batches still running
  const [failed, setFailed] = useState<string[]>([]);
  const [sort, setSort] = useState<Sort>("price");
  const [hover, setHover] = useState<string | null>(null);
  // kept in USD so switching currency keeps the same limit
  const [maxUsd, setMaxUsd] = useState<number | null>(null);
  const maxPrice = maxUsd == null ? null : convert(maxUsd, "USD");
  const [when, setWhen] = useState<"any" | "mine">("any");
  const listRef = useRef<HTMLDivElement>(null);

  const nights = roundTrip ? Math.max(1, dayDiff(depart, ret)) : null;
  // Exact dates still explore a few days around them; flexibility widens it.
  const win = Math.max(2, flex);
  const spread = Math.max(1, flex + retFlex);
  const key = JSON.stringify([origins, depart, nights, win, spread, currency]);

  useEffect(() => {
    const codes = expandCodes(origins).slice(0, 2);
    if (!codes.length) return;
    const ctl = new AbortController();
    const t = setTimeout(async () => {
      setItems(new Map());
      setFailed([]);
      const merged = new Map<string, Destination>();
      const keep = (d: Destination) => {
        const cur = merged.get(d.destination);
        if (!cur || convert(d.price, d.currency, "USD") < convert(cur.price, cur.currency, "USD")) merged.set(d.destination, d);
      };
      // Instant: destinations pre-computed by the tracker (Google Explore).
      try {
        const cached = await api<{ items: Destination[] }>(`/explore/cached?origins=${codes.join(",")}`, { signal: ctl.signal });
        cached.items.forEach(keep);
        if (merged.size) setItems(new Map(merged));
      } catch {
        /* no cache yet */
      }
      const body = (origin: string, batch: number) => ({
        origin,
        start: addDays(depart, -win),
        end: addDays(depart, win),
        currency,
        nights_min: nights ? Math.max(1, nights - spread) : null,
        nights_max: nights ? nights + spread : null,
        batch,
      });
      // batch 0: fast worldwide sources (Kiwi web, KAYAK, Ryanair) in ~3 s;
      // batch 1: the slower Kiwi continent lookups for extra depth.
      for (const batch of [0, 1]) {
        if (ctl.signal.aborted) return;
        setLoading(2 - batch);
        const res = await Promise.allSettled(
          codes.map((o) => api<{ items: Destination[]; errors?: Record<string, string> }>("/explore", { body: body(o, batch), signal: ctl.signal })),
        );
        if (ctl.signal.aborted) return;
        for (const r of res) {
          if (r.status === "rejected") {
            setFailed((f) => [...f, (r.reason as Error).message]);
            continue;
          }
          for (const [src, msg] of Object.entries(r.value.errors ?? {})) setFailed((f) => [...f, `${src}: ${msg}`]);
          r.value.items.forEach(keep);
        }
        setItems(new Map(merged));
      }
      setLoading(0);
    }, 600);
    return () => {
      clearTimeout(t);
      ctl.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const all = useMemo(() => [...items.values()].filter((d) => !origins.includes(d.destination)), [items, origins]);
  const range = useMemo(() => {
    const ps = all.map((d) => convert(d.price, d.currency));
    return ps.length ? [Math.floor(Math.min(...ps)), Math.ceil(Math.max(...ps))] : [0, 0];
  }, [all, convert]);
  const list = useMemo(() => {
    const lo = addDays(depart, -win);
    const hi = addDays(depart, win);
    const arr = all.filter(
      (d) =>
        (maxPrice == null || convert(d.price, d.currency) <= maxPrice) &&
        (when === "any" || (d.departure != null && d.departure >= lo && d.departure <= hi)),
    );
    return arr.sort((a, b) =>
      sort === "price" ? convert(a.price, a.currency, "USD") - convert(b.price, b.currency, "USD") : (a.departure ?? "").localeCompare(b.departure ?? ""),
    );
  }, [all, sort, convert, maxPrice, when, depart, win]);

  const scale = useMemo(() => priceScale(list.map((d) => convert(d.price, d.currency))), [list, convert]);
  const city = (d: Destination) => d.city || airport(d.destination)?.city || d.destination;

  const points = useMemo<MapPoint[]>(() => {
    // Every destination gets a price label; overlapping ones collapse to dots
    // (cheapest win) and reappear as you zoom in. The hovered row goes first.
    const ordered = hover ? [...list.filter((d) => d.destination === hover), ...list.filter((d) => d.destination !== hover)] : list;
    const pts: MapPoint[] = ordered.map((d) => {
      const p = convert(d.price, d.currency);
      return {
        code: d.destination,
        lat: d.lat,
        lon: d.lon,
        label: `${city(d)} ${money(d.price, d.currency)}`,
        title: `${city(d)} (${d.destination}) · ${money(d.price, d.currency)}${d.departure ? ` · ${formatDate(d.departure, false)}` : ""}. Click to search flights.`,
        color: scale.solid(p),
        onClick: () => onPick(d),
      };
    });
    for (const o of expandCodes(origins)) pts.push({ code: o, tone: "origin", label: airport(o)?.city ?? o });
    return pts;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [list, scale, hover, origins, money]);

  if (!origins.length) return null;

  return (
    <section className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold">
          Cheapest places from {origins.map((o) => airport(o)?.city ?? o).join(" or ")}
        </h2>
        <Segmented
          size="sm"
          value={when}
          onChange={setWhen}
          options={[
            { value: "any", label: "Any dates" },
            { value: "mine", label: `Around ${formatDate(depart, false)}` },
          ]}
        />
        {loading > 0 && (
          <span className="inline-flex items-center gap-1.5 text-xs text-muted">
            <Spinner /> {list.length ? "finding more destinations" : "looking everywhere"}
          </span>
        )}
        {failed.length > 0 && loading === 0 && (
          <span className="inline-flex items-center gap-1 text-xs text-faint" title={[...new Set(failed)].join("\n")}>
            <Info className="size-3.5" /> Some sources didn&apos;t respond, results may be incomplete
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">
          {range[1] > range[0] && (
            <label className="flex h-7 items-center gap-2 rounded-md bg-surface-2 px-2 text-xs text-muted">
              <span className="whitespace-nowrap">Under {money(maxPrice ?? range[1], currency)}</span>
              <input
                type="range"
                min={range[0]}
                max={range[1]}
                step={Math.max(1, Math.round((range[1] - range[0]) / 100))}
                value={maxPrice ?? range[1]}
                onChange={(e) => setMaxUsd(Number(e.target.value) >= range[1] ? null : convert(Number(e.target.value), currency, "USD"))}
                className="w-28 accent-[var(--accent)]"
                aria-label="Maximum price"
              />
            </label>
          )}
          <Segmented
            size="sm"
            value={sort}
            onChange={setSort}
            options={[
              { value: "price", label: "Cheapest" },
              { value: "date", label: "Soonest" },
            ]}
          />
        </div>
      </div>
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_380px]">
        <RouteMap points={points} className="h-72 rounded-2xl lg:h-[560px]" fitKey={key + (list.length > 0 ? "1" : "0")} />
        <div ref={listRef} className="max-h-[560px] space-y-1 overflow-y-auto pr-1">
          {!list.length &&
            loading > 0 &&
            Array.from({ length: 8 }).map((_, i) => <div key={i} className="h-14 animate-pulse rounded-xl bg-surface-2" />)}
          {!list.length && loading === 0 && <div className="p-6 text-center text-sm text-muted">No destinations found for these dates.</div>}
          {list.map((d) => {
            const p = convert(d.price, d.currency);
            const n = d.departure && d.return_date ? dayDiff(d.departure, d.return_date) : null;
            return (
              <div
                key={d.destination}
                onMouseEnter={() => setHover(d.destination)}
                onMouseLeave={() => setHover(null)}
                className={cn(
                  "group flex cursor-pointer items-center gap-3 rounded-xl border border-border bg-surface px-3 py-2 transition-colors hover:border-border-strong",
                  hover === d.destination && "border-border-strong",
                )}
                onClick={() => onPick(d)}
              >
                <span className="size-2.5 shrink-0 rounded-full" style={{ background: scale.solid(p) }} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5 text-sm font-medium">
                    <span className="truncate">{city(d)}</span>
                    <span className="font-mono text-xs text-muted">{d.destination}</span>
                    <span onClick={(e) => e.stopPropagation()}>
                      <StarButton code={d.destination} />
                    </span>
                  </div>
                  <div className="text-xs text-muted">
                    {formatDate(d.departure)}
                    {n != null && ` · ${n} nights`} · from {d.origin}
                  </div>
                </div>
                <div className="text-right">
                  <div className="font-semibold tabular-nums" style={{ color: scale.color(p) }}>
                    {money(d.price, d.currency)}
                  </div>
                  {d.booking_url && (
                    <a
                      href={d.booking_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      onClick={(e) => e.stopPropagation()}
                      className="inline-flex items-center gap-0.5 text-xs text-muted hover:text-fg"
                    >
                      Book <ExternalLink className="size-3" />
                    </a>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
