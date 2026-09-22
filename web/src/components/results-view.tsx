"use client";
import { useMemo, useState } from "react";
import { ExternalLink, Info } from "lucide-react";
import { TripCard } from "./trip-card";
import { RouteMap, type MapArc, type MapPoint } from "./route-map";
import { useApp } from "./app-context";
import { useWatchDialog } from "./watch-dialog";
import { Badge, Empty, Segmented, Select, Switch } from "./ui";
import { tripBlocked } from "@/lib/sellers";
import { parseLocal, dayDiff } from "@/lib/format";
import type { PlanResult, SearchQuery, SearchResult, Trip } from "@/lib/types";

type Sort = "price" | "duration" | "departure" | "best";

function tripDuration(t: Trip) {
  if (t.tickets.length === 1) return t.tickets[0].slices[0].duration_min;
  return t.travel_min;
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
  const [maxStops, setMaxStops] = useState<string>("any");
  const [showSplit, setShowSplit] = useState(true);
  const [hideSelfTransfer, setHideSelfTransfer] = useState(false);
  const [timeOfDay, setTimeOfDay] = useState("any");
  const [sources, setSources] = useState<string[]>([]);
  const [hover, setHover] = useState<Trip | null>(null);
  const rules = useMemo(() => settings?.sellerRules ?? [], [settings]);

  const allSources = useMemo(() => [...new Set(trips.flatMap((t) => t.tickets.map((x) => x.source)))], [trips]);
  const blocked = trips.filter((t) => tripBlocked(rules, t)).length;

  const list = useMemo(() => {
    const cheapest = Math.min(...trips.map((t) => convert(t.total_price, t.currency, "USD")));
    const fastest = Math.min(...trips.map(tripDuration));
    const f = trips.filter((t) => {
      if (tripBlocked(rules, t)) return false;
      if (!showSplit && t.tickets.length > 1) return false;
      if (hideSelfTransfer && t.tickets.some((x) => x.self_transfer)) return false;
      if (maxStops !== "any" && tripStops(t) > Number(maxStops)) return false;
      if (sources.length && !t.tickets.every((x) => sources.includes(x.source))) return false;
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
      return score(a) - score(b);
    });
  }, [trips, rules, showSplit, hideSelfTransfer, maxStops, sources, timeOfDay, sort, convert]);

  const shown = list.slice(0, 80);
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
  const direct = plan?.direct;

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_380px]">
      <div className="min-w-0 space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <Segmented
            size="sm"
            value={sort}
            onChange={setSort}
            options={[
              { value: "price", label: "Cheapest" },
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
            {list.length} of {trips.length} options
          </span>
          {blocked > 0 && <span>{blocked} hidden by your seller rules</span>}
          {direct && (
            <span>
              Cheapest single ticket: <span className="font-medium text-fg">{direct.total_price.toFixed(0)} {direct.currency}</span>
            </span>
          )}
          {plan && plan.hubs_tried.length > 0 && (
            <span title={plan.hubs_tried.join(", ")}>
              Smart routes tried {plan.hubs_tried.length} hubs in {plan.requests} searches
            </span>
          )}
          {googleUrl && (
            <a href={googleUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-accent hover:underline">
              Open this search on Google Flights <ExternalLink className="size-3" />
            </a>
          )}
        </div>
        {errors && Object.keys(errors).length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(errors).map(([k, v]) => (
              <Badge key={k} tone="warn" title={v}>
                <Info className="size-3" /> {k}: {v.length > 80 ? v.slice(0, 80) + "…" : v}
              </Badge>
            ))}
          </div>
        )}
        {!shown.length ? (
          <Empty title="No flights match">Try loosening the filters, adding nearby airports, or turning on smart routes.</Empty>
        ) : (
          <div className="space-y-2">
            {shown.map((t) => (
              <TripCard
                key={t.id}
                trip={t}
                highlight={hover?.id === t.id}
                onHover={setHover}
                onWatch={(trip) => {
                  const out = trip.tickets.flatMap((x) => x.slices).sort((a, b) => a.departure.localeCompare(b.departure));
                  const dep = out[0].departure.slice(0, 10);
                  const ret = trip.route.at(-1) === trip.route[0] ? out.at(-1)!.departure.slice(0, 10) : null;
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
                  }, trips);
                }}
              />
            ))}
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
  );
}
