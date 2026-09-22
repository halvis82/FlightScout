// Watch logic shared by the server (signed in users) and the browser (guests).
import { addDays, dayDiff, formatPrice } from "./format";
import type { Cabin, SearchQuery, Trip } from "./types";

export type WatchLike = {
  origins: string[];
  destinations: string[];
  tripType: "oneway" | "roundtrip";
  departStart: string;
  departEnd: string;
  nightsMin: number | null;
  nightsMax: number | null;
  cabin: string;
  adults: number;
  maxStops: number | null;
  currency: string;
  alertBelow: number | null;
  alertDropPct: number | null;
  name: string;
};

export type ObservationInput = {
  observed_at?: string;
  depart_date: string;
  return_date?: string | null;
  price: number;
  currency: string;
  source: string;
  kind?: string;
  route?: string | null;
  duration_min?: number | null;
  booking_url?: string | null;
  trip?: unknown;
};

// One engine query covering a watch's date window. Google gets the middle
// date, Kiwi covers the rest of the window through flex days.
export function watchToQuery(w: WatchLike): SearchQuery {
  const today = new Date().toISOString().slice(0, 10);
  const start = w.departStart < today ? today : w.departStart;
  const span = Math.max(0, dayDiff(start, w.departEnd));
  const half = Math.floor(span / 2);
  const departure = addDays(start, half);
  const nMin = w.nightsMin ?? 7;
  const nMax = w.nightsMax ?? nMin;
  const nights = Math.round((nMin + nMax) / 2);
  return {
    origins: w.origins,
    destinations: w.destinations,
    departure,
    return_date: w.tripType === "roundtrip" ? addDays(departure, nights) : null,
    adults: w.adults,
    cabin: w.cabin as Cabin,
    max_stops: w.maxStops,
    currency: w.currency,
    sources: ["google", "kiwi"],
    departure_flex_days: Math.min(10, span - half),
    return_flex_days: w.tripType === "roundtrip" ? Math.min(10, Math.ceil((nMax - nMin) / 2)) : 0,
  };
}

// Engine trips to observation rows. Full trip JSON is kept only for the
// cheapest few so history stays compact.
export function tripsToObservations(trips: Trip[], destinations: string[] = [], keepTrips = 3): ObservationInput[] {
  const sorted = [...trips].sort((a, b) => a.total_price - b.total_price);
  return sorted.map((t, i) => {
    const slices = t.tickets.flatMap((x) => x.slices).sort((a, b) => a.departure.localeCompare(b.departure));
    const home = t.route[0];
    const roundTrip = t.route.at(-1) === home && slices.length > 1;
    // The return starts at the first slice leaving the destination (or, if
    // unknown, the last slice heading home).
    const back = roundTrip
      ? (slices.find((s) => destinations.includes(s.origin)) ?? slices.findLast((s) => s.destination === home))
      : undefined;
    const sources = [...new Set(t.tickets.map((x) => x.source))];
    return {
      depart_date: (slices[0]?.departure ?? t.departure).slice(0, 10),
      return_date: back ? back.departure.slice(0, 10) : null,
      price: t.total_price,
      currency: t.currency,
      source: sources.length === 1 ? sources[0] : sources.join("+"),
      kind: t.kind,
      route: t.route.join("-"),
      duration_min: t.travel_min,
      booking_url: t.tickets[0]?.booking_url ?? null,
      trip: i < keepTrips ? t : null,
    };
  });
}

// Why (if at all) a new best price should alert. Empty when it shouldn't.
export function alertReasons(w: WatchLike, price: number, prev: number | null): string[] {
  const reasons: string[] = [];
  if (w.alertBelow != null && price <= w.alertBelow && (prev == null || prev > w.alertBelow)) {
    reasons.push(`is now ${formatPrice(price, w.currency)}, below your ${formatPrice(w.alertBelow, w.currency)} target`);
  }
  if (w.alertDropPct != null && prev != null && price <= prev * (1 - w.alertDropPct / 100)) {
    const pct = Math.round((1 - price / prev) * 100);
    reasons.push(`dropped ${pct}% from ${formatPrice(prev, w.currency)} to ${formatPrice(price, w.currency)}`);
  }
  return reasons;
}

export function queryMatchesWatch(q: SearchQuery, w: WatchLike & { active?: boolean }) {
  const overlap = (a: string[], b: string[]) => a.some((x) => b.includes(x));
  if (w.active === false) return false;
  if (!overlap(q.origins, w.origins) || !overlap(q.destinations, w.destinations)) return false;
  if (q.departure < w.departStart || q.departure > w.departEnd) return false;
  if ((w.tripType === "roundtrip") !== Boolean(q.return_date)) return false;
  if (w.cabin !== (q.cabin ?? "economy")) return false;
  return true;
}
