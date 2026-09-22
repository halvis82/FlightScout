import { and, asc, eq, gte } from "drizzle-orm";
import { db, schema } from "@/lib/db";
import { intParam, json, requireUser, route } from "@/lib/api";
import { convertWith, getRates } from "@/lib/fx";
import { ownWatch } from "@/lib/watches";

type Ctx = { params: Promise<{ id: string }> };

// Every observation for the watch, converted to the watch currency.
// ?days=N limits how far back (default 365).
export const GET = route<Ctx>(async (req, { params }) => {
  const userId = await requireUser(req);
  const w = await ownWatch(userId, intParam((await params).id));
  const days = Number(new URL(req.url).searchParams.get("days") ?? 365);
  const since = new Date(Date.now() - days * 86400_000);
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
      has_trip: schema.observations.trip,
    })
    .from(schema.observations)
    .where(and(eq(schema.observations.watchId, w.id), gte(schema.observations.observedAt, since)))
    .orderBy(asc(schema.observations.observedAt));
  const rates = await getRates();
  return json({
    watch: w,
    observations: rows.map(({ has_trip, ...r }) => ({
      ...r,
      has_trip: has_trip != null,
      value: Math.round(convertWith(rates, r.price, r.currency, w.currency) * 100) / 100,
    })),
  });
});
