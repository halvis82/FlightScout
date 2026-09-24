import "server-only";
import { createHash } from "node:crypto";
import { and, eq, gt, lt } from "drizzle-orm";
import { db, schema } from "./db";

// How long a result may be reused. Prices move, so searches are short lived;
// calendars and explore change slowly.
const TTL_MIN: Record<string, number> = { search: 20, plan: 60, multicity: 30, trip: 60, dates: 360, explore: 180 };

function stable(v: unknown): unknown {
  if (Array.isArray(v)) return v.map(stable);
  if (v && typeof v === "object")
    return Object.fromEntries(
      Object.entries(v as Record<string, unknown>)
        .filter(([, x]) => x !== undefined && x !== null)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([k, x]) => [k, stable(x)]),
    );
  return v;
}

export function cacheKey(kind: string, body: Record<string, unknown>) {
  return createHash("sha256").update(kind + JSON.stringify(stable(body))).digest("hex");
}

export async function cacheGet(kind: string, key: string): Promise<Record<string, unknown> | null> {
  const ttl = TTL_MIN[kind];
  if (!ttl) return null;
  try {
    const since = new Date(Date.now() - ttl * 60_000);
    const [row] = await db
      .select({ payload: schema.searchCache.payload, createdAt: schema.searchCache.createdAt })
      .from(schema.searchCache)
      .where(and(eq(schema.searchCache.key, key), gt(schema.searchCache.createdAt, since)));
    return row ? { ...(row.payload as Record<string, unknown>), cached_at: row.createdAt } : null;
  } catch {
    return null; // the cache is an optimization; never fail a search because of it
  }
}

export async function cachePut(kind: string, key: string, payload: unknown) {
  if (!TTL_MIN[kind]) return;
  try {
    await db
      .insert(schema.searchCache)
      .values({ key, kind, payload, createdAt: new Date() })
      .onConflictDoUpdate({ target: schema.searchCache.key, set: { payload, createdAt: new Date() } });
    // opportunistic cleanup of anything older than a day
    if (Math.random() < 0.05) await db.delete(schema.searchCache).where(lt(schema.searchCache.createdAt, new Date(Date.now() - 86_400_000)));
  } catch {
    /* ignore */
  }
}
