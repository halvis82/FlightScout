"use client";
import { Fragment, useMemo, useState } from "react";
import { ExternalLink, Info } from "lucide-react";
import { PartySize, TripCard } from "./trip-card";
import { RouteMap, type MapArc, type MapPoint } from "./route-map";
import { useApp } from "./app-context";
import { useWatchDialog } from "./watch-dialog";
import { Button, Empty, Segmented, Select, Switch } from "./ui";
import { tripBlocked } from "@/lib/sellers";
import { inCurrency } from "@/lib/airlines";
import { parseLocal, dayDiff } from "@/lib/format";
import type { PlanResult, SearchQuery, SearchResult, Trip } from "@/lib/types";

type Sort = "price" | "duration" | "departure" | "best";

const SOURCE_NAMES: Record<string, string> = { google: "Google Flights", kiwi: "Kiwi", kiwiweb: "Kiwi", serpapi: "Google (paid)" };

// Filter chips group the ~40 sources into what people care about.
function sourceGroup(tk: { source: string; seller_kind?: string }) {
  if (tk.source === "google" || tk.source === "serpapi") return "Google Flights";
  if (tk.source === "kiwi" || tk.source === "kiwiweb") return "Kiwi";
  return tk.seller_kind === "airline" ? "Airlines direct" : "Booking sites";
}

function tripDuration(t: Trip) {
  if (t.tickets.length === 1) return t.tickets[0].slices[0].duration_min;
  return t.travel_min;
}

// Position on Google's "Best" tab: top flights first, then its other flights.
function googleRank(t: Trip) {
  const tk = t.tickets.length === 1 ? t.tickets[0] : null;
  if (!tk || tk.source !== "google" || tk.google_rank == null) return Infinity;
  return (tk.google_top ? 0 : 10_000) + tk.google_rank;
}

function tripStops(t: Trip) {
  if (t.tickets.length === 1) return t.tickets[0].slices[0].stops;
  return t.tickets.reduce((s, x) => s + x.slices[0].stops, 0) + t.tickets.length - 1;
}

// Merge direct search results with smart routes, drop duplicates.
export function mergeTrips(search?: SearchResult | null, plan?: PlanResult | null): Trip[] {
  const out = new Map<string, Trip>();
  for (const t of search?.trips ?? []) out.set(t.id, t);
  for (const t of plan?.trips ?? []) if (!out.has(t.id)) out.set(t.id, t);
  return [...out.values()];
}

export function ResultsView({
  trips,
  query,
  errors,
  googleUrl,
  plan,
}: {
  trips: Trip[];
  query?: Partial<SearchQuery> | null;
  errors?: Record<string, string>;
  googleUrl?: string | null;
  plan?: PlanResult | null;
}) {
  const { settings, convert } = useApp();
  const watch = useWatchDialog();
  const [sort, setSort] = useState<Sort>("price");
  // starts at the search's own stops limit and follows it when it changes
  const qStops = query?.max_stops == null ? "any" : String(query.max_stops);
  const [maxStops, setMaxStops] = useState<string>(qStops);
  const [stopsFor, setStopsFor] = useState(qStops);
  if (stopsFor !== qStops) {
    setStopsFor(qStops);
    setMaxStops(qStops);
  }
  const [showSplit, setShowSplit] = useState(true);
  const [hideSelfTransfer, setHideSelfTransfer] = useState(false);
  const [timeOfDay, setTimeOfDay] = useState("any");
  const [sources, setSources] = useState<string[]>([]);
  const [hover, setHover] = useState<Trip | null>(null);
  // kept in USD so switching currency keeps the same limit
  const [maxUsd, setMaxUsd] = useState<number | null>(null);
  const maxPrice = maxUsd == null ? null : convert(maxUsd, "USD");
  const [limit, setLimit] = useState(60);
  const { money } = useApp();
  // a new search starts with clean filters (a source or price limit from the
  // last one could hide every result, with its control no longer shown)
  const searchKey = JSON.stringify([query?.origins, query?.destinations, query?.departure, query?.return_date, query?.adults]);
  const [filtersFor, setFiltersFor] = useState(searchKey);
  if (filtersFor !== searchKey) {
    setFiltersFor(searchKey);
    setSources([]);
    setMaxUsd(null);
    setLimit(60);
  }
  const resetFilters = () => {
    setSources([]);
    setMaxUsd(null);
    setMaxStops("any");
    setTimeOfDay("any");
    setShowSplit(true);
    setHideSelfTransfer(false);
  };
  const priceRange = useMemo(() => {
    const ps = trips.map((t) => convert(t.total_price, t.currency));
    return ps.length ? [Math.floor(Math.min(...ps)), Math.ceil(Math.max(...ps))] : [0, 0];
  }, [trips, convert]);
  const rules = useMemo(() => settings?.sellerRules ?? [], [settings]);

  const allSources = useMemo(() => [...new Set(trips.flatMap((t) => t.tickets.map(sourceGroup)))], [trips]);
  const blocked = trips.filter((t) => tripBlocked(rules, t)).length;
  // only filters whose control is on screen apply
  const activeKey = allSources.length > 1 ? sources.filter((s) => (allSources as string[]).includes(s)).join(",") : "";
  const activeMax = priceRange[1] > priceRange[0] ? maxPrice : null;

  const list = useMemo(() => {
    const cheapest = Math.min(...trips.map((t) => convert(t.total_price, t.currency, "USD")));
    const fastest = Math.min(...trips.map(tripDuration));
    const f = trips.filter((t) => {
      if (tripBlocked(rules, t)) return false;
      if (activeMax != null && convert(t.total_price, t.currency) > activeMax) return false;
      if (!showSplit && t.tickets.length > 1) return false;
      if (hideSelfTransfer && t.tickets.some((x) => x.self_transfer)) return false;
      if (maxStops !== "any" && tripStops(t) > Number(maxStops)) return false;
      if (activeKey && !t.tickets.every((x) => activeKey.split(",").includes(sourceGroup(x)))) return false;
      if (timeOfDay !== "any") {
        const h = parseLocal(t.departure).h;
        if (timeOfDay === "morning" && (h < 5 || h >= 12)) return false;
        if (timeOfDay === "afternoon" && (h < 12 || h >= 18)) return false;
        if (timeOfDay === "evening" && h < 18 && h >= 5) return false;
      }
      return true;
    });
    const score = (t: Trip) => {
      const p = convert(t.total_price, t.currency, "USD") / cheapest;
      const d = tripDuration(t) / fastest;
      return p * 0.65 + d * 0.3 + (t.tickets.length - 1) * 0.08 + (t.tickets.some((x) => x.self_transfer) ? 0.05 : 0);
    };
    return f.sort((a, b) => {
      if (sort === "price") return convert(a.total_price, a.currency, "USD") - convert(b.total_price, b.currency, "USD");
      if (sort === "duration") return tripDuration(a) - tripDuration(b);
      if (sort === "departure") return a.departure.localeCompare(b.departure);
      // Best: Google's own "Best" order first (top flights, then the rest of
      // its list), everything else after by price and time.
      const ra = googleRank(a);
      const rb = googleRank(b);
      if (ra !== rb) return ra - rb;
      if (ra !== Infinity) return convert(a.total_price, a.currency, "USD") - convert(b.total_price, b.currency, "USD");
      return score(a) - score(b);
    });
  }, [trips, rules, showSplit, hideSelfTransfer, maxStops, activeKey, timeOfDay, sort, convert, activeMax]);

  // One row per outbound flight (like Google): the same outbound paired with
  // different returns collapses into its best pairing, the others become
  // "other returns" inside the card.
  const grouped = useMemo(() => {
    const byOut = new Map<string, { trip: Trip; alts: Trip[] }>();
    const order: string[] = [];
    for (const t of list) {
      const single = t.tickets.length === 1 && t.tickets[0].slices.length === 2 ? t.tickets[0] : null;
      const key = single
        ? single.slices[0].segments.map((x) => `${x.carrier}${x.flight_number}@${x.departure}`).join("|") + "#" + single.source
        : t.id;
      const g = byOut.get(key);
      if (g) g.alts.push(t);
      else {
        byOut.set(key, { trip: t, alts: [] });
        order.push(key);
      }
    }
    return order.map((k) => byOut.get(k)!);
  }, [list]);

  const shown = grouped.slice(0, limit).map((g) => g.trip);
  const focus = hover ?? shown[0];

  const { arcs, points } = useMemo(() => {
    const arcs: MapArc[] = [];
    const seen = new Set<string>();
    for (const t of shown.slice(0, 12)) {
      if (t === focus) continue;
      for (const sl of t.tickets.flatMap((x) => x.slices))
        for (const s of sl.segments) {
          const k = s.origin + s.destination;
          if (!seen.has(k)) {
            seen.add(k);
            arcs.push({ from: s.origin, to: s.destination, tone: "muted" });
          }
        }
    }
    const pts = new Map<string, MapPoint>();
    if (focus) {
      focus.tickets.forEach((tk, i) =>
        tk.slices.forEach((sl) =>
          sl.segments.forEach((s) => arcs.push({ from: s.origin, to: s.destination, tone: i % 2 ? "alt" : "primary", dashed: tk.self_transfer })),
        ),
      );
      focus.route.forEach((c, i) =>
        pts.set(c, { code: c, tone: i === 0 ? "origin" : c === focus.route.at(-1) || query?.destinations?.includes(c) ? "dest" : "hub" }),
      );
    }
    return { arcs, points: [...pts.values()] };
  }, [shown, focus, query]);

  const splitCount = trips.filter((t) => t.tickets.length > 1).length;
  // Like Google's "Cheapest from $X" tab
  const low = list.length ? Math.min(...list.map((t) => convert(t.total_price, t.currency))) : null;
  const cheapestLabel =
    low == null ? "Cheapest" : (
      <>
        Cheapest <span className="font-normal text-muted">from</span> {money(low, settings?.currency ?? "USD")}
      </>
    );
  const hasTop = sort === "best" && grouped.some((g) => g.trip.tickets[0]?.google_top);
  const direct = plan?.direct;

  return (
    <PartySize.Provider value={query?.adults ?? 1}>
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_380px]">
      <div className="min-w-0 space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <Segmented
            size="sm"
            value={sort}
            onChange={setSort}
            options={[
              { value: "price", label: cheapestLabel },
              { value: "best", label: "Best" },
              { value: "duration", label: "Fastest" },
              { value: "departure", label: "Earliest" },
            ]}
          />
          <Select className="h-7 text-xs" value={maxStops} onChange={(e) => setMaxStops(e.target.value)}>
            <option value="any">Any stops</option>
            <option value="0">Nonstop</option>
            <option value="1">1 stop max</option>
            <option value="2">2 stops max</option>
          </Select>
          <Select className="h-7 text-xs" value={timeOfDay} onChange={(e) => setTimeOfDay(e.target.value)}>
            <option value="any">Any time</option>
            <option value="morning">Morning departure</option>
            <option value="afternoon">Afternoon departure</option>
            <option value="evening">Evening or night</option>
          </Select>
          {priceRange[1] > priceRange[0] && (
            <label className="flex h-7 items-center gap-2 rounded-md bg-surface-2 px-2 text-xs text-muted">
              <span className="whitespace-nowrap">Under {money(maxPrice ?? priceRange[1], settings?.currency ?? "USD")}</span>
              <input
                type="range"
                min={priceRange[0]}
                max={priceRange[1]}
                step={Math.max(1, Math.round((priceRange[1] - priceRange[0]) / 100))}
                value={maxPrice ?? priceRange[1]}
                onChange={(e) => setMaxUsd(Number(e.target.value) >= priceRange[1] ? null : convert(Number(e.target.value), settings?.currency ?? "USD", "USD"))}
                className="w-28 accent-[var(--accent)]"
                aria-label="Maximum price"
              />
            </label>
          )}
          {allSources.length > 1 &&
            allSources.map((s) => (
              <button
                key={s}
                onClick={() => setSources((x) => (x.includes(s) ? x.filter((y) => y !== s) : [...x, s]))}
                className={`h-7 rounded-md border px-2 text-xs ${sources.includes(s) ? "border-accent bg-accent-soft text-accent" : "border-border text-muted"}`}
              >
                {s}
              </button>
            ))}
          {splitCount > 0 && <Switch checked={showSplit} onChange={setShowSplit} label={<span className="text-xs">Split tickets ({splitCount})</span>} />}
          <Switch checked={hideSelfTransfer} onChange={setHideSelfTransfer} label={<span className="text-xs">Hide self transfers</span>} />
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
          <span>
            {grouped.length} flights{grouped.length !== trips.length ? ` (${trips.length} combinations)` : ""}
          </span>
          {blocked > 0 && <span>{blocked} hidden by your seller rules</span>}
          <span title="Options found per source. Google includes the flights from its Cheapest tab.">
            {Object.entries(
              trips.reduce<Record<string, number>>((acc, t) => {
                for (const tk of t.tickets) {
                  const name = SOURCE_NAMES[tk.source] ?? (tk.seller_kind === "ota" ? (tk.seller ?? tk.source) : "Airlines direct");
                  acc[name] = (acc[name] ?? 0) + 1;
                }
                return acc;
              }, {}),
            )
              .sort((a, b) => b[1] - a[1])
              .map(([k, v]) => `${k} ${v}`)
              .join(" · ")}
          </span>
          {(query?.adults ?? 1) > 1 && <span>Prices are the total for all {query!.adults} travelers</span>}
          {direct && (
            <span>
              Cheapest single ticket: <span className="font-medium text-fg">{money(direct.total_price, direct.currency)}</span>
            </span>
          )}
          {plan && plan.hubs_tried.length > 0 && (
            <span title={plan.hubs_tried.join(", ")}>
              Smart routes tried {plan.hubs_tried.length} hubs in {plan.requests} searches
            </span>
          )}
          {googleUrl && (
            <a href={inCurrency(googleUrl, settings?.currency ?? "USD")} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-accent hover:underline">
              Open this search on Google Flights <ExternalLink className="size-3" />
            </a>
          )}
        </div>
        {errors && Object.keys(errors).length > 0 && (
          <div className="flex items-center gap-1 text-xs text-faint" title={Object.entries(errors).map(([k, v]) => `${k}: ${v}`).join("\n")}>
            <Info className="size-3.5" /> Some sources didn&apos;t respond, results may be incomplete
          </div>
        )}
        {(() => {
          const singles = list.filter((t) => t.kind === "single");
          const combos = list.filter((t) => t.kind !== "single" && t.kind !== "nearby");
          if (!singles.length || !combos.length) return null;
          const bestSingle = Math.min(...singles.map((t) => convert(t.total_price, t.currency)));
          const best = combos.reduce((a, b) => (convert(a.total_price, a.currency) <= convert(b.total_price, b.currency) ? a : b));
          const save = bestSingle - convert(best.total_price, best.currency);
          if (save < 10) return null;
          return (
            <div className="rounded-2xl border border-good/40 bg-good-soft/40 p-2">
              <div className="flex items-center gap-2 px-2 pb-2 pt-1 text-sm">
                <span className="font-semibold text-good">Cheaper combination: save {money(save, settings?.currency ?? "USD")}</span>
                <span className="text-muted">vs the cheapest single ticket, by booking {best.tickets.length} tickets separately</span>
              </div>
              <TripCard trip={best} highlight={hover?.id === best.id} onHover={setHover} />
            </div>
          );
        })()}
        {!shown.length ? (
          <Empty
            title="No flights match"
            action={
              trips.length > blocked ? (
                <Button size="sm" onClick={resetFilters}>
                  Clear filters
                </Button>
              ) : undefined
            }
          >
            {trips.length > blocked ? "The filters hide every flight." : "Try adding nearby airports or turning on smart routes."}
          </Empty>
        ) : (
          <div className="space-y-2">
            {grouped.slice(0, limit).map(({ trip: t, alts }, i, arr) => (
              <Fragment key={t.id}>
                {hasTop && i === 0 && t.tickets[0]?.google_top && (
                  <h3 className="px-1 pt-1 text-sm font-semibold">
                    Top departing flights <span className="font-normal text-muted">as ranked on Google Flights</span>
                  </h3>
                )}
                {hasTop && !t.tickets[0]?.google_top && (i === 0 || arr[i - 1].trip.tickets[0]?.google_top) && (
                  <h3 className="px-1 pt-3 text-sm font-semibold">Other departing flights</h3>
                )}
              <TripCard
                trip={t}
                alts={alts}
                highlight={hover?.id === t.id}
                onHover={setHover}
                onWatch={(trip) => {
                  const out = trip.tickets.flatMap((x) => x.slices).sort((a, b) => a.departure.localeCompare(b.departure));
                  const dep = out[0].departure.slice(0, 10);
                  // the search's own trip type (a return to another airport of the same city is still a round trip)
                  const rt = query?.return_date != null || trip.route.at(-1) === trip.route[0];
                  const ret = rt ? (out.length > 1 ? out.at(-1)!.departure.slice(0, 10) : (query?.return_date ?? null)) : null;
                  const nights = ret ? dayDiff(dep, ret) : null;
                  watch.open({
                    origins: query?.origins ?? [trip.route[0]],
                    destinations: query?.destinations ?? [trip.route.at(-1)!],
                    trip_type: ret ? "roundtrip" : "oneway",
                    depart_start: dep,
                    depart_end: dep,
                    nights_min: nights,
                    nights_max: nights,
                    currency: trip.currency,
                    include_split: trip.tickets.length > 1,
                    alert_below: Math.floor(trip.total_price * 0.9),
                    cabin: query?.cabin ?? "economy",
                    adults: query?.adults ?? 1,
                    max_stops: query?.max_stops ?? null,
                  }, trips);
                }}
              />
              </Fragment>
            ))}
            {grouped.length > limit && (
              <Button className="w-full" onClick={() => setLimit(grouped.length)}>
                Show all {grouped.length} results
              </Button>
            )}
          </div>
        )}
      </div>
      <div className="order-first lg:order-none">
        <div className="lg:sticky lg:top-16">
          <RouteMap arcs={arcs} points={points} className="h-64 lg:h-[420px]" fitKey={shown[0]?.id} />
          {focus && (
            <p className="mt-2 text-xs text-muted">
              Showing {hover ? "the hovered option" : "the top option"}. Dashed lines are self transfers. Hover a result to preview its route.
            </p>
          )}
        </div>
      </div>
      {watch.element}
    </div>
    </PartySize.Provider>
  );
}
