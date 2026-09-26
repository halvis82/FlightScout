import { eq } from "drizzle-orm";
import { db, schema } from "@/lib/db";
import { json, requireTracker, route } from "@/lib/api";
import { DEFAULT_PLANNER } from "@/lib/settings";

// Every active watch across all users, with the owner's planner defaults, for
// the scheduled tracker (GitHub Actions).
export const GET = route(async (req) => {
  requireTracker(req);
  const rows = await db
    .select({ w: schema.watches, planner: schema.settings.planner, rules: schema.settings.sellerRules })
    .from(schema.watches)
    .leftJoin(schema.settings, eq(schema.settings.userId, schema.watches.userId))
    .where(eq(schema.watches.active, true));
  const today = new Date().toISOString().slice(0, 10);
  return json(
    rows
      .filter((r) => r.w.departEnd >= today)
      .map(({ w, planner, rules }) => ({
        id: w.id,
        name: w.name,
        origins: w.origins,
        destinations: w.destinations,
        trip_type: w.tripType,
        legs: w.legs,
        depart_start: w.departStart < today ? today : w.departStart,
        depart_end: w.departEnd,
        nights_min: w.nightsMin,
        nights_max: w.nightsMax,
        cabin: w.cabin,
        adults: w.adults,
        max_stops: w.maxStops,
        currency: w.currency,
        include_split: w.includeSplit,
        last_checked_at: w.lastCheckedAt,
        planner: { ...DEFAULT_PLANNER, ...(planner ?? {}) },
        // the owner's hidden sellers stay hidden in tracked prices too
        seller_rules: Object.fromEntries((rules ?? []).filter((r) => r.mode === "block").map((r) => [r.seller, r.mode])),
      })),
  );
});
