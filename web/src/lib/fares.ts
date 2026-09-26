import "server-only";
import { and, between, eq, sql } from "drizzle-orm";
import { db, schema } from "./db";
import { convertWith, getRates, hasRate } from "./fx";
import { isDate } from "./watch-validate";
import type { Trip } from "./types";

// Shared fare memory (see schema.fareMemory): one way tickets from every
// result this site sees, cheapest per route and day, kept two weeks.
const KEEP_DAYS = 14;

export async function recordFares(trips: Trip[] | undefined) {
  if (!Array.isArray(trips) || !trips.length) return;
  try {
    const rates = await getRates();
    const today = new Date().toISOString().slice(0, 10);
    const best = new Map<string, { origin: string; dest: string; day: string; usd: number }>();
    for (const t of trips) {
      for (const tk of t?.tickets ?? []) {
        // only well formed, future, convertible one way tickets (results can come from any client)
        if (tk?.slices?.length !== 1 || tk.return_pending || !(typeof tk.price === "number" && tk.price > 0) || !hasRate(rates, tk.currency)) continue;
        const sl = tk.slices[0];
        const day = typeof sl?.departure === "string" ? sl.departure.slice(0, 10) : "";
        if (!/^[A-Z]{3}$/.test(sl?.origin ?? "") || !/^[A-Z]{3}$/.test(sl?.destination ?? "") || !isDate(day) || day < today) continue;
        const usd = convertWith(rates, tk.price, tk.currency, "USD");
        if (!Number.isFinite(usd) || usd < 5 || usd > 50_000) continue;
        const row = { origin: sl.origin, dest: sl.destination, day, usd: Math.round(usd * 100) / 100 };
        const k = `${row.origin}>${row.dest}@${row.day}`;
        if (!best.has(k) || best.get(k)!.usd > row.usd) best.set(k, row);
      }
    }
    if (!best.size) return;
    await db
      .insert(schema.fareMemory)
      .values([...best.values()].slice(0, 500))
      .onConflictDoUpdate({
        target: [schema.fareMemory.origin, schema.fareMemory.dest, schema.fareMemory.day],
        // the cheapest of this batch replaces what was known (fares move)
        set: { usd: sql`excluded.usd`, seenAt: sql`now()` },
      });
    // prune now and then
    if (Math.random() < 0.02) await db.delete(schema.fareMemory).where(sql`${schema.fareMemory.seenAt} < now() - interval '${sql.raw(String(KEEP_DAYS))} days'`);
  } catch (e) {
    console.error("fare memory write failed", e);
  }
}

// Cheapest known USD price from `origin` to every destination, and to `dest`
// from every origin, departing lo..hi: hints for the planner's layovers.
export async function knownFares(origin: string, dest: string, lo: string, hi: string) {
  const fresh = sql`${schema.fareMemory.seenAt} > now() - interval '${sql.raw(String(KEEP_DAYS))} days'`;
  try {
    const [from, to] = await Promise.all([
      db
        .select({ code: schema.fareMemory.dest, usd: sql<number>`min(${schema.fareMemory.usd})` })
        .from(schema.fareMemory)
        .where(and(eq(schema.fareMemory.origin, origin), between(schema.fareMemory.day, lo, hi), fresh))
        .groupBy(schema.fareMemory.dest)
        .limit(400),
      db
        .select({ code: schema.fareMemory.origin, usd: sql<number>`min(${schema.fareMemory.usd})` })
        .from(schema.fareMemory)
        .where(and(eq(schema.fareMemory.dest, dest), between(schema.fareMemory.day, lo, hi), fresh))
        .groupBy(schema.fareMemory.origin)
        .limit(400),
    ]);
    return {
      known_from_origin: Object.fromEntries(from.map((r) => [r.code, Number(r.usd)])),
      known_to_dest: Object.fromEntries(to.map((r) => [r.code, Number(r.usd)])),
    };
  } catch (e) {
    console.error("fare memory read failed", e);
    return { known_from_origin: {}, known_to_dest: {} };
  }
}
