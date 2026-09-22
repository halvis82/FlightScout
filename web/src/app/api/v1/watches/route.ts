import { and, desc, eq, gte, inArray, sql } from "drizzle-orm";
import { db, schema } from "@/lib/db";
import { body, json, requireUser, route } from "@/lib/api";
import { getRates, convertWith } from "@/lib/fx";
import { getSettings } from "@/lib/settings";
import { toColumns, type WatchIn } from "@/lib/watch-validate";

export const GET = route(async (req) => {
  const userId = await requireUser(req);
  const ws = await db
    .select()
    .from(schema.watches)
    .where(eq(schema.watches.userId, userId))
    .orderBy(desc(schema.watches.active), desc(schema.watches.createdAt));
  if (!ws.length) return json([]);
  // Daily minimum (in USD) for the last 90 days feeds each card's sparkline.
  const since = new Date(Date.now() - 90 * 86400_000);
  const day = sql<string>`to_char(date_trunc('day', ${schema.observations.observedAt}), 'YYYY-MM-DD')`;
  const pts = await db
    .select({ watchId: schema.observations.watchId, day, min: sql<number>`min(${schema.observations.priceUsd})` })
    .from(schema.observations)
    .where(and(inArray(schema.observations.watchId, ws.map((w) => w.id)), gte(schema.observations.observedAt, since)))
    .groupBy(schema.observations.watchId, day)
    .orderBy(day);
  const rates = await getRates();
  return json(
    ws.map((w) => ({
      ...w,
      sparkline: pts
        .filter((p) => p.watchId === w.id)
        .map((p) => ({ day: p.day, price: Math.round(convertWith(rates, Number(p.min), "USD", w.currency)) })),
    })),
  );
});

export const POST = route(async (req) => {
  const userId = await requireUser(req);
  const p = await body<WatchIn>(req);
  if (!p.currency) p.currency = (await getSettings(userId)).currency;
  const cols = toColumns(p, false);
  const [row] = await db
    .insert(schema.watches)
    .values({ ...(cols as typeof schema.watches.$inferInsert), userId })
    .returning();
  return json(row, 201);
});
