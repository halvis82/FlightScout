import "server-only";
import { and, desc, eq, gte } from "drizzle-orm";
import { db, schema } from "./db";
import { feedMatchingWatches } from "./observations";
import type { SearchQuery, Trip } from "./types";

type Kind = "search" | "plan" | "explore" | "dates" | "trip" | "multicity";
type Origin = "web" | "cli" | "mcp" | "tracker" | "local";

export function summarize(kind: Kind, q: Record<string, unknown>): string {
  const list = (v: unknown) => (Array.isArray(v) ? v.join("/") : typeof v === "string" ? v : "?");
  if (kind === "explore") return `Explore from ${list(q.origin ?? q.origins)} ${q.start ?? ""} to ${q.end ?? ""}`.trim();
  if (kind === "dates") return `Date prices ${list(q.origin)} to ${list(q.destination)}`;
  if (kind === "trip") {
    const stops = Array.isArray(q.stops) ? (q.stops as { place: string }[]).map((s) => s.place).join(", ") : "";
    return `Trip from ${list(q.start)} via ${stops}${q.earliest_departure ? ` from ${q.earliest_departure}` : ""}`;
  }
  const from = list(q.origins ?? q.origin);
  const to = list(q.destinations ?? q.destination);
  const dep = (q.departure ?? q.depart_start) as string | undefined;
  const ret = (q.return_date ?? q.return_start) as string | undefined;
  return `${kind === "plan" ? "Smart routes " : ""}${from} to ${to}${dep ? ` ${dep}` : ""}${ret ? ` to ${ret}` : ""}`;
}

// The same search again within this window (a reload, back and forth) updates
// its history row instead of adding another.
const SAME_SEARCH_MS = 30 * 60_000;

// Save a search to history and, when it produced trips, feed matching watches.
export async function saveSearch(
  userId: string,
  kind: Kind,
  origin: Origin,
  query: Record<string, unknown>,
  payload: unknown,
) {
  // a search also saves its smart routes, so look through the recent rows, not just the last one
  const recent = await db
    .select({ id: schema.searches.id, query: schema.searches.query })
    .from(schema.searches)
    .where(and(eq(schema.searches.userId, userId), eq(schema.searches.kind, kind), gte(schema.searches.createdAt, new Date(Date.now() - SAME_SEARCH_MS))))
    .orderBy(desc(schema.searches.id))
    .limit(20);
  const last = recent.find((r) => stable(r.query) === stable(query));
  let id: number;
  if (last) {
    id = last.id;
    await db.update(schema.searches).set({ payload: payload as object, createdAt: new Date() }).where(eq(schema.searches.id, id));
  } else {
    const [row] = await db
      .insert(schema.searches)
      .values({ userId, kind, origin, summary: summarize(kind, query), query, payload: payload as object })
      .returning({ id: schema.searches.id });
    id = row.id;
  }
  const watchesUpdated = await feed(userId, kind, query, (payload as { trips?: Trip[] } | null)?.trips);
  return { id, watchesUpdated };
}

// A streamed search saves its first part, then the whole result once every
// part is in: store that and feed watches the trips they haven't seen yet.
export async function extendSearch(userId: string, id: number, payload: { trips?: Trip[] }) {
  const [row] = await db
    .select()
    .from(schema.searches)
    .where(and(eq(schema.searches.id, id), eq(schema.searches.userId, userId)));
  if (!row || row.kind !== "search" || !Array.isArray(payload?.trips)) return null;
  const had = new Set(((row.payload as { trips?: Trip[] } | null)?.trips ?? []).map((t) => t.id));
  await db.update(schema.searches).set({ payload: payload as object }).where(eq(schema.searches.id, id));
  const fresh = payload.trips.filter((t) => !had.has(t.id));
  return { id, watchesUpdated: await feed(userId, "search", row.query as Record<string, unknown>, fresh) };
}

async function feed(userId: string, kind: Kind, query: Record<string, unknown>, trips: Trip[] | undefined) {
  let watchesUpdated = 0;
  if ((kind === "search" || kind === "plan") && Array.isArray(trips) && trips.length) {
    const q: SearchQuery =
      kind === "search"
        ? (query as unknown as SearchQuery)
        : {
            origins: query.origins as string[],
            destinations: query.destinations as string[],
            departure: query.depart_start as string,
            return_date: (query.return_start as string) ?? null,
            cabin: (query.cabin as SearchQuery["cabin"]) ?? "economy",
          };
    try {
      watchesUpdated = await feedMatchingWatches(userId, q, trips);
    } catch (e) {
      console.error("feeding watches failed", e);
    }
  }
  return watchesUpdated;
}

// Key order independent (Postgres jsonb reorders keys).
function stable(v: unknown): string {
  if (Array.isArray(v)) return `[${v.map(stable).join(",")}]`;
  if (v && typeof v === "object")
    return `{${Object.keys(v)
      .sort()
      .filter((k) => (v as Record<string, unknown>)[k] !== undefined)
      .map((k) => `${JSON.stringify(k)}:${stable((v as Record<string, unknown>)[k])}`)
      .join(",")}}`;
  return JSON.stringify(v);
}
