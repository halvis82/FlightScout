import { and, isNotNull, lt, sql } from "drizzle-orm";
import { db, schema } from "@/lib/db";
import { json, route, HttpError } from "@/lib/api";

// Daily housekeeping (vercel.json cron). Keeps the free Postgres tier small:
// drops full trip JSON from observations older than 30 days (prices stay),
// trims search payloads older than 180 days, and read alerts older than 90.
export const GET = route(async (req) => {
  const secret = process.env.CRON_SECRET;
  if (!secret || req.headers.get("authorization") !== `Bearer ${secret}`) throw new HttpError(401, "unauthorized");
  const day = 86400_000;
  const obs = await db
    .update(schema.observations)
    .set({ trip: null })
    .where(and(isNotNull(schema.observations.trip), lt(schema.observations.observedAt, new Date(Date.now() - 30 * day))));
  await db
    .update(schema.searches)
    .set({ payload: sql`null` })
    .where(lt(schema.searches.createdAt, new Date(Date.now() - 180 * day)));
  await db
    .delete(schema.alerts)
    .where(and(isNotNull(schema.alerts.readAt), lt(schema.alerts.createdAt, new Date(Date.now() - 90 * day))));
  await db.delete(schema.rateLimits).where(lt(schema.rateLimits.windowStart, new Date(Date.now() - 2 * 3600_000)));
  return json({ ok: true, obs: (obs as unknown as { count?: number }).count ?? null });
});
