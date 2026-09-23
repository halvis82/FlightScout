import { db, schema } from "@/lib/db";
import { HttpError, json, requireTracker, route } from "@/lib/api";

export const POST = route(async (req) => {
  requireTracker(req);
  const body = (await req.json()) as { origin?: string; currency?: string; items?: unknown[] };
  if (!body.origin || !Array.isArray(body.items)) throw new HttpError(400, "origin and items are required");
  const row = { origin: body.origin.toUpperCase(), currency: body.currency ?? "USD", items: body.items, updatedAt: new Date() };
  await db
    .insert(schema.exploreCache)
    .values(row)
    .onConflictDoUpdate({ target: schema.exploreCache.origin, set: { currency: row.currency, items: row.items, updatedAt: row.updatedAt } });
  return json({ ok: true, count: body.items.length });
});
