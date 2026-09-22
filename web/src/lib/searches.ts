import "server-only";
import { db, schema } from "./db";
import { feedMatchingWatches } from "./observations";
import type { SearchQuery, Trip } from "./types";

type Kind = "search" | "plan" | "explore" | "dates" | "trip";
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

// Save a search to history and, when it produced trips, feed matching watches.
export async function saveSearch(
  userId: string,
  kind: Kind,
  origin: Origin,
  query: Record<string, unknown>,
  payload: unknown,
) {
  const [row] = await db
    .insert(schema.searches)
    .values({ userId, kind, origin, summary: summarize(kind, query), query, payload: payload as object })
    .returning({ id: schema.searches.id });
  let watchesUpdated = 0;
  const trips = (payload as { trips?: Trip[] } | null)?.trips;
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
  return { id: row.id, watchesUpdated };
}
