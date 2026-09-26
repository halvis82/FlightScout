// Watch logic shared by the server (signed in users) and the browser (guests).
import { addDays, dayDiff, formatPrice, isoDate } from "./format";
import { expandCodes } from "./metros";
import type { Cabin, SearchQuery, Trip } from "./types";

export type WatchLike = {
  origins: string[];
  destinations: string[];
  tripType: "oneway" | "roundtrip" | "multicity";
  legs?: unknown;
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
  const today = isoDate(new Date());
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
    // a round trip "from" price (return picked on the booking page) still
    // belongs to the return date it was searched for, not to "one way"
    const pendingReturn = t.tickets[0]?.return_pending ? (t.tickets[0].pending_return ?? null) : null;
    return {
      depart_date: (slices[0]?.departure ?? t.departure).slice(0, 10),
      return_date: back ? back.departure.slice(0, 10) : pendingReturn,
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
  // a multi city watch is priced leg by leg, never by an ordinary search
  if (w.tripType === "multicity") return false;
  if (!overlap(q.origins, w.origins) || !overlap(q.destinations, w.destinations)) return false;
  if (q.departure < w.departStart || q.departure > w.departEnd) return false;
  if ((w.tripType === "roundtrip") !== Boolean(q.return_date)) return false;
  if (w.cabin !== (q.cabin ?? "economy")) return false;
  // prices are for the whole party and depend on stops and trip length
  if ((w.adults ?? 1) !== (q.adults ?? 1)) return false;
  if ((w.maxStops ?? null) !== (q.max_stops ?? null)) return false;
  if (w.tripType === "roundtrip" && q.return_date) {
    const n = Math.round((Date.parse(q.return_date) - Date.parse(q.departure)) / 86400_000);
    if (w.nightsMin != null && n < w.nightsMin) return false;
    if (w.nightsMax != null && n > w.nightsMax) return false;
  }
  return true;
}

// The trips of a matching search that this watch actually covers: from one of
// its airports to one of its destinations, leaving in its window, and for
// round trips back home after a stay it allows. A search can cover more
// (other airports, dates or trip lengths) than the watch does.
export function tripsForWatch(trips: Trip[], w: WatchLike): Trip[] {
  const from = new Set(expandCodes(w.origins));
  const to = new Set(expandCodes(w.destinations));
  return trips.filter((t) => {
    const slices = t.tickets.flatMap((x) => x.slices).sort((a, b) => a.departure.localeCompare(b.departure));
    if (!slices.length) return false;
    const dep = slices[0].departure.slice(0, 10);
    if (!from.has(slices[0].origin) || dep < w.departStart || dep > w.departEnd) return false;
    const pending = t.tickets[0]?.return_pending;
    // one way (also split into several tickets): ends at a destination
    if (w.tripType === "oneway") return !pending && to.has(slices.at(-1)!.destination);
    // round trip: out to a destination, then home again after the allowed stay
    const out = slices.findIndex((s) => to.has(s.destination));
    if (out < 0) return false;
    let ret: string | null = null;
    if (pending) ret = t.tickets[0].pending_return ?? null;
    else {
      const back = slices.slice(out + 1).find((s) => to.has(s.origin));
      if (!back || !from.has(slices.at(-1)!.destination)) return false;
      ret = back.departure.slice(0, 10);
    }
    if (!ret) return false;
    const n = dayDiff(dep, ret);
    if (w.nightsMin != null && n < w.nightsMin) return false;
    if (w.nightsMax != null && n > w.nightsMax) return false;
    return true;
  });
}

// How often a watch is checked, honestly: accounts get the twice daily
// tracker, guest watches live in the browser.
export function checkNote(guest: boolean) {
  return guest
    ? "Prices are recorded when you search it or press Check now; sign in for automatic checks twice a day."
    : "Prices are checked twice a day.";
}
