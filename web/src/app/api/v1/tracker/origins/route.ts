import { desc, eq, sql } from "drizzle-orm";
import { db, schema } from "@/lib/db";
import { json, requireTracker, route } from "@/lib/api";

// Airports to warm the explore cache for: every user's homes and favorites,
// plus origins explored recently.
export const GET = route(async (req) => {
  requireTracker(req);
  const places = await db
    .select({ codes: schema.places.codes })
    .from(schema.places)
    .where(sql`${schema.places.kind} in ('home', 'frequent')`);
  const recent = await db
    .select({ query: schema.searches.query })
    .from(schema.searches)
    .where(eq(schema.searches.kind, "explore"))
    .orderBy(desc(schema.searches.createdAt))
    .limit(50);
  const out = new Set<string>();
  for (const p of places) for (const c of p.codes) if (/^[A-Z]{3}$/.test(c)) out.add(c);
  for (const r of recent) {
    const o = (r.query as { origin?: string }).origin;
    if (o && /^[A-Z]{3}$/.test(o)) out.add(o);
  }
  return json([...out]);
});
