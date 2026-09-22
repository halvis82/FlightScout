import "server-only";
import { sql } from "drizzle-orm";
import { db, schema } from "./db";
import { HttpError } from "./api";

export type EngineKind = "search" | "plan" | "explore" | "dates" | "trip";

// Requests per hour. Guests are limited per IP, signed in users per account.
const LIMITS: Record<EngineKind, { guest: number; user: number }> = {
  search: { guest: 30, user: 300 },
  plan: { guest: 5, user: 40 },
  trip: { guest: 5, user: 40 },
  explore: { guest: 20, user: 200 },
  dates: { guest: 20, user: 200 },
};

const WINDOW_MS = 3600_000;

// In memory fallback when the database is unreachable.
const mem = new Map<string, { start: number; count: number }>();

export function clientIp(req: Request) {
  const h = req.headers;
  return (
    h.get("x-real-ip") ??
    h.get("x-forwarded-for")?.split(",")[0]?.trim() ??
    h.get("cf-connecting-ip") ??
    "unknown"
  );
}

export async function enforceRateLimit(req: Request, kind: EngineKind, userId: string | null) {
  const limit = userId ? LIMITS[kind].user : LIMITS[kind].guest;
  const key = `${kind}:${userId ? `u:${userId}` : `ip:${clientIp(req)}`}`;
  const windowStart = new Date(Math.floor(Date.now() / WINDOW_MS) * WINDOW_MS);
  let count: number;
  try {
    const [row] = await db
      .insert(schema.rateLimits)
      .values({ key, windowStart, count: 1 })
      .onConflictDoUpdate({
        target: [schema.rateLimits.key, schema.rateLimits.windowStart],
        set: { count: sql`${schema.rateLimits.count} + 1` },
      })
      .returning({ count: schema.rateLimits.count });
    count = row.count;
  } catch {
    const m = mem.get(key);
    if (!m || m.start !== windowStart.getTime()) mem.set(key, { start: windowStart.getTime(), count: 1 });
    else m.count++;
    count = mem.get(key)!.count;
  }
  if (count > limit) {
    const mins = Math.ceil((windowStart.getTime() + WINDOW_MS - Date.now()) / 60000);
    throw new HttpError(
      429,
      userId
        ? `You've hit the limit of ${limit} ${kind} requests per hour. Try again in ${mins} minutes.`
        : `Guests can run ${limit} ${kind} requests per hour. Try again in ${mins} minutes, or sign in for higher limits.`,
    );
  }
}
