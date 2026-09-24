import "server-only";
import { sql } from "drizzle-orm";
import { db, schema } from "./db";
import { HttpError } from "./api";

export type EngineKind = "search" | "plan" | "explore" | "dates" | "trip" | "multicity" | "browser";

// Requests per hour. Guests are limited per IP, signed in users per account.
const LIMITS: Record<EngineKind, { guest: number; user: number }> = {
  search: { guest: 60, user: 400 },
  plan: { guest: 12, user: 80 },
  trip: { guest: 5, user: 40 },
  multicity: { guest: 8, user: 60 },
  // Google via the visitor's own browser: only parsing happens here, so these
  // are cheap (a round trip search is 2-3 calls)
  browser: { guest: 200, user: 1000 },
  explore: { guest: 40, user: 300 },
  dates: { guest: 60, user: 400 },
};

// Follow up explore batches (1 and 2) of the same interaction have their own
// looser bucket so one explore counts as one unit against the explore limit.
const EXPLORE_MORE = { guest: 60, user: 600 };

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

export async function enforceRateLimit(req: Request, kind: EngineKind, userId: string | null, followUp = false) {
  const lim = followUp && kind === "explore" ? EXPLORE_MORE : LIMITS[kind];
  const limit = userId ? lim.user : lim.guest;
  const key = `${kind}${followUp ? "+" : ""}:${userId ? `u:${userId}` : `ip:${clientIp(req)}`}`;
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
