import "server-only";
import { and, asc, desc, eq, gte } from "drizzle-orm";
import { db, schema } from "./db";
import { convertWith, getRates, hasRate } from "./fx";
import { isDate } from "./watch-validate";
import { sendEmail, sendPush } from "./notify";
import { getSettings } from "./settings";
import { formatPrice } from "./format";
import type { Trip, SearchQuery } from "./types";
import { alertReasons, queryMatchesWatch, tripsForWatch, tripsToObservations, type ObservationInput } from "./watch-logic";

export type { ObservationInput };

type Watch = typeof schema.watches.$inferSelect;

export async function recordObservations(watch: Watch, obs: ObservationInput[]) {
  const rates = await getRates();
  const now = new Date();
  const today = now.toISOString().slice(0, 10);
  // only real, future prices in a currency we can compare; timestamps can't
  // be moved into the future or far back
  const good = obs.filter(
    (o) => o && typeof o.price === "number" && Number.isFinite(o.price) && o.price > 0 && isDate(o.depart_date) && o.depart_date >= today && hasRate(rates, o.currency),
  );
  if (!good.length) {
    await db.update(schema.watches).set({ lastCheckedAt: now }).where(eq(schema.watches.id, watch.id));
    return { inserted: 0, alerts: 0 };
  }
  const clamp = (t?: string | null) => {
    const ms = t ? Date.parse(t) : NaN;
    return Number.isFinite(ms) ? new Date(Math.min(now.getTime(), Math.max(now.getTime() - 7 * 86400_000, ms))) : now;
  };
  const rows = good.map((o) => ({
    watchId: watch.id,
    observedAt: clamp(o.observed_at),
    departDate: o.depart_date,
    returnDate: isDate(o.return_date) ? o.return_date : null,
    price: o.price,
    currency: o.currency.toUpperCase(),
    priceUsd: convertWith(rates, o.price, o.currency, "USD"),
    source: String(o.source ?? "").slice(0, 80),
    kind: o.kind ?? "single",
    route: o.route ?? null,
    durationMin: o.duration_min ?? null,
    bookingUrl: o.booking_url ?? null,
    trip: o.trip ?? null,
  }));
  await db.insert(schema.observations).values(rows);

  // The current best is the cheapest of every fresh price (the last day, for
  // dates still ahead), not just this batch: a search covering one date must
  // not make the watch look more expensive (and later "drop").
  const since = new Date(Math.max(now.getTime() - 24 * 3600_000, watch.pricesSince ? new Date(watch.pricesSince).getTime() : 0));
  const [top] = await db
    .select()
    .from(schema.observations)
    .where(and(eq(schema.observations.watchId, watch.id), gte(schema.observations.observedAt, since), gte(schema.observations.departDate, today)))
    .orderBy(asc(schema.observations.priceUsd))
    .limit(1);
  if (!top || top.priceUsd == null) return { inserted: rows.length, alerts: 0 };
  const bestVal = Math.round(convertWith(rates, top.priceUsd, "USD", watch.currency) * 100) / 100;
  const prev = watch.bestPrice;
  const lowest = watch.lowestPrice == null ? bestVal : Math.min(watch.lowestPrice, bestVal);
  await db
    .update(schema.watches)
    .set({
      prevPrice: prev,
      bestPrice: bestVal,
      lowestPrice: lowest,
      bestTrip: top.trip ?? watch.bestTrip,
      lastCheckedAt: now,
    })
    .where(eq(schema.watches.id, watch.id));

  const alerts = await evaluateAlerts(watch, bestVal, prev, { booking_url: top.bookingUrl } as ObservationInput);
  return { inserted: rows.length, alerts };
}

// A price target set (or lowered) while the current best already meets it
// would never alert, because alerts fire when a price crosses the target.
// Alert right away instead.
export async function alertIfTargetMet(before: Watch, after: Watch) {
  if (after.alertBelow == null || after.alertBelow === before.alertBelow || after.bestPrice == null || after.bestPrice > after.alertBelow) return 0;
  const url = (after.bestTrip as Trip | null)?.tickets?.[0]?.booking_url ?? null;
  return evaluateAlerts(after, after.bestPrice, null, { booking_url: url } as ObservationInput);
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
    if (!queryMatchesWatch(q, w)) continue;
    const mine = tripsForWatch(trips, w);
    if (!mine.length) continue;
    await recordObservations(w, tripsToObservations(mine, w.destinations));
    n++;
  }
  return n;
}
