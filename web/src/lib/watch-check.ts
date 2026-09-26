import "server-only";
import { db, schema } from "./db";
import { engine } from "./engine";
import { addDays } from "./format";
import { watchToQuery } from "./watch-logic";
import { recordObservations } from "./observations";
import { tripsForWatch, tripsToObservations } from "./watch-logic";
import { getSettings } from "./settings";
import type { PlanResult, SearchResult, Trip } from "./types";

type Watch = typeof schema.watches.$inferSelect;

export async function checkWatch(w: Watch, userId: string) {
  if (w.tripType === "multicity" && w.legs?.length) {
    const res = await engine<PlanResult>("/multicity", { legs: w.legs, currency: w.currency, cabin: w.cabin, adults: w.adults });
    const dest = [w.legs.at(-1)!.destinations[0]];
    const result = await recordObservations(w, tripsToObservations(res.trips.slice(0, 5), dest));
    await db.insert(schema.searches).values({
      userId,
      kind: "multicity",
      origin: "web",
      summary: `Watch check: ${w.name}`,
      query: { legs: w.legs },
      payload: res,
    });
    return { ...result, trips: res.trips.length, errors: res.errors };
  }
  const q = watchToQuery(w);
  const s = await getSettings(userId);
  const blocked = s.sellerRules.filter((r) => r.mode === "block");
  const res = await engine<SearchResult>("/search", {
    ...q,
    ...(blocked.length ? { seller_rules: Object.fromEntries(blocked.map((r) => [r.seller, r.mode])) } : {}),
  });
  let trips: Trip[] = res.trips;
  const errors = { ...res.errors };
  if (w.includeSplit) {
    try {
      const plan = await engine<PlanResult>("/plan", {
        origins: w.origins,
        destinations: w.destinations,
        depart_start: w.departStart,
        depart_end: w.departEnd,
        return_start: q.return_date ? addDays(w.departStart, w.nightsMin ?? 7) : null,
        return_end: q.return_date ? addDays(w.departEnd, w.nightsMax ?? w.nightsMin ?? 7) : null,
        currency: w.currency,
        cabin: w.cabin,
        adults: w.adults,
        // the owner's limits, clamped like the website's own automatic searches
        max_stopover_days: Math.min(s.planner.max_stopover_days, 3),
        min_connection_hours: s.planner.min_connection_hours,
        max_trip_days: s.planner.max_trip_days,
        max_hubs: Math.min(s.planner.max_hubs, 6),
        allow_self_transfer: s.planner.allow_self_transfer,
        include_nested_roundtrips: s.planner.include_nested_roundtrips,
      });
      trips = [...trips, ...plan.trips.filter((t) => t.tickets.length > 1)];
      Object.assign(errors, plan.errors);
    } catch (e) {
      errors.plan = (e as Error).message;
    }
  }
  const result = await recordObservations(w, tripsToObservations(tripsForWatch(trips, w), w.destinations));
  await db.insert(schema.searches).values({
    userId,
    kind: "search",
    origin: "web",
    summary: `Watch check: ${w.name}`,
    query: q,
    payload: { ...res, trips, errors },
  });
  return { ...result, trips: trips.length, errors };
}
