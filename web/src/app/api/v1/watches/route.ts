import { and, desc, eq, gte, inArray, sql } from "drizzle-orm";
import { db, schema } from "@/lib/db";
import { body, json, requireUser, route } from "@/lib/api";
import { getRates, convertWith } from "@/lib/fx";
import { getSettings } from "@/lib/settings";
import { checkWatch, toColumns, type WatchIn } from "@/lib/watch-validate";
import { watchSignature } from "@/lib/signature";

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
    // the full best trip stays on the watch's own page (it's large and the list doesn't show it)
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    ws.map(({ bestTrip, ...w }) => ({
      ...w,
      sparkline: pts
        .filter((p) => p.watchId === w.id && (!w.pricesSince || p.day >= new Date(w.pricesSince).toISOString().slice(0, 10)))
        .map((p) => ({ day: p.day, price: Math.round(convertWith(rates, Number(p.min), "USD", w.currency)) })),
    })),
  );
});

export const POST = route(async (req) => {
  const userId = await requireUser(req);
  const p = await body<WatchIn>(req);
  if (!p.currency) p.currency = (await getSettings(userId)).currency;
  const cols = toColumns(p, false) as typeof schema.watches.$inferInsert;
  checkWatch(cols as { departStart: string; departEnd: string });
  const signature = watchSignature({ ...cols, departStart: cols.departStart as string });
  // Same search saved twice (double click, retry, CLI): return the existing one.
  // Rows saved before signatures were canonical are compared recomputed.
  const mine = await db.select().from(schema.watches).where(eq(schema.watches.userId, userId));
  const same = mine.find((w) => w.signature === signature || watchSignature({ ...w, departStart: String(w.departStart), departEnd: w.departEnd ? String(w.departEnd) : null }) === signature);
  if (same) return json({ ...same, existing: true }, 200);
  const [row] = await db
    .insert(schema.watches)
    .values({ ...cols, userId, signature })
    .onConflictDoNothing({ target: [schema.watches.userId, schema.watches.signature] })
    .returning();
  if (row) return json(row, 201);
  const [existing] = await db
    .select()
    .from(schema.watches)
    .where(and(eq(schema.watches.userId, userId), eq(schema.watches.signature, signature)));
  return json({ ...existing, existing: true }, 200);
});
