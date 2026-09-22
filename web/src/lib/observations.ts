import "server-only";
import { and, desc, eq, gte } from "drizzle-orm";
import { db, schema } from "./db";
import { convertWith, getRates } from "./fx";
import { sendEmail, sendPush } from "./notify";
import { getSettings } from "./settings";
import { formatPrice } from "./format";
import type { Trip, SearchQuery } from "./types";
import { alertReasons, queryMatchesWatch, tripsToObservations, type ObservationInput } from "./watch-logic";

export type { ObservationInput };

type Watch = typeof schema.watches.$inferSelect;

export async function recordObservations(watch: Watch, obs: ObservationInput[]) {
  if (!obs.length) return { inserted: 0, alerts: 0 };
  const rates = await getRates();
  const now = new Date();
  const rows = obs.map((o) => ({
    watchId: watch.id,
    observedAt: o.observed_at ? new Date(o.observed_at) : now,
    departDate: o.depart_date,
    returnDate: o.return_date ?? null,
    price: o.price,
    currency: o.currency,
    priceUsd: convertWith(rates, o.price, o.currency, "USD"),
    source: o.source,
    kind: o.kind ?? "single",
    route: o.route ?? null,
    durationMin: o.duration_min ?? null,
    bookingUrl: o.booking_url ?? null,
    trip: o.trip ?? null,
  }));
  await db.insert(schema.observations).values(rows);

  // Current best of this batch, in the watch currency.
  let best = obs[0];
  let bestVal = Infinity;
  for (const o of obs) {
    const v = convertWith(rates, o.price, o.currency, watch.currency);
    if (v < bestVal) {
      bestVal = v;
      best = o;
    }
  }
  const prev = watch.bestPrice;
  const lowest = watch.lowestPrice == null ? bestVal : Math.min(watch.lowestPrice, bestVal);
  await db
    .update(schema.watches)
    .set({
      prevPrice: prev,
      bestPrice: bestVal,
      lowestPrice: lowest,
      bestTrip: best.trip ?? watch.bestTrip,
      lastCheckedAt: now,
    })
    .where(eq(schema.watches.id, watch.id));

  const alerts = await evaluateAlerts(watch, bestVal, prev, best);
  return { inserted: rows.length, alerts };
}

async function evaluateAlerts(watch: Watch, price: number, prev: number | null, best: ObservationInput) {
  const reasons = alertReasons(watch, price, prev);
  if (!reasons.length) return 0;

  // Don't repeat the same alert more than once every 12 hours.
  const since = new Date(Date.now() - 12 * 3600_000);
  const [recent] = await db
    .select()
    .from(schema.alerts)
    .where(and(eq(schema.alerts.watchId, watch.id), gte(schema.alerts.createdAt, since)))
    .orderBy(desc(schema.alerts.createdAt))
    .limit(1);
  if (recent && recent.price != null && recent.price <= price) return 0;

  const message = `${watch.name} ${reasons.join(" and ")}`;
  await db.insert(schema.alerts).values({
    userId: watch.userId,
    watchId: watch.id,
    message,
    price,
    currency: watch.currency,
    bookingUrl: best.booking_url ?? null,
  });
  const s = await getSettings(watch.userId);
  const base = process.env.BETTER_AUTH_URL ?? "";
  if (s.pushAlerts) {
    await sendPush(watch.userId, { title: "FlightScout price alert", body: message, url: `/watches/${watch.id}` });
  }
  if (s.emailAlerts) {
    const [u] = await db.select().from(schema.user).where(eq(schema.user.id, watch.userId));
    if (u) {
      await sendEmail(
        u.email,
        `Price alert: ${watch.name} ${formatPrice(price, watch.currency)}`,
        `<p>${message}.</p><p><a href="${best.booking_url ?? base + "/watches/" + watch.id}">Open the fare</a> · <a href="${base}/watches/${watch.id}">View price history</a></p>`,
      );
    }
  }
  return 1;
}

export async function feedMatchingWatches(userId: string, q: SearchQuery, trips: Trip[]) {
  if (!trips.length) return 0;
  const ws = await db
    .select()
    .from(schema.watches)
    .where(and(eq(schema.watches.userId, userId), eq(schema.watches.active, true)));
  let n = 0;
  for (const w of ws) {
    if (queryMatchesWatch(q, w)) {
      await recordObservations(w, tripsToObservations(trips, w.destinations));
      n++;
    }
  }
  return n;
}
