import { and, asc, eq, gte, sql } from "drizzle-orm";
import { db, schema } from "@/lib/db";
import { numParam, intParam, json, requireUser, route } from "@/lib/api";
import { convertWith, getRates } from "@/lib/fx";
import { ownWatch } from "@/lib/watches";

type Ctx = { params: Promise<{ id: string }> };

// Every observation for the watch, converted to the watch currency.
// ?days=N limits how far back (default 365).
export const GET = route<Ctx>(async (req, { params }) => {
  const userId = await requireUser(req);
  const w = await ownWatch(userId, intParam((await params).id));
  const days = numParam(new URL(req.url).searchParams, "days", 365, 1, 3650);
  // prices from before the watch last changed (route, dates, party, currency) describe another search
  const since = new Date(Math.max(Date.now() - days * 86400_000, w.pricesSince ? new Date(w.pricesSince).getTime() : 0));
  const rows = await db
    .select({
      id: schema.observations.id,
      observed_at: schema.observations.observedAt,
      depart_date: schema.observations.departDate,
      return_date: schema.observations.returnDate,
      price: schema.observations.price,
      currency: schema.observations.currency,
      source: schema.observations.source,
      kind: schema.observations.kind,
      route: schema.observations.route,
      duration_min: schema.observations.durationMin,
      booking_url: schema.observations.bookingUrl,
      has_trip: sql<boolean>`${schema.observations.trip} is not null`,
    })
    .from(schema.observations)
    .where(and(eq(schema.observations.watchId, w.id), gte(schema.observations.observedAt, since)))
    .orderBy(asc(schema.observations.observedAt))
    .limit(20_000);
  const rates = await getRates();
  return json({
    watch: w,
    observations: rows.map(({ has_trip, ...r }) => ({
      ...r,
      has_trip: Boolean(has_trip),
      value: Math.round(convertWith(rates, r.price, r.currency, w.currency) * 100) / 100,
    })),
  });
});
