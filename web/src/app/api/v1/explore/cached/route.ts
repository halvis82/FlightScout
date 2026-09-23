import { inArray } from "drizzle-orm";
import { db, schema } from "@/lib/db";
import { json, route } from "@/lib/api";

// Pre-computed explore results (public, no rate limit): shown instantly while
// live explore runs.
export const GET = route(async (req) => {
  const origins = (new URL(req.url).searchParams.get("origins") ?? "")
    .split(",")
    .map((s) => s.trim().toUpperCase())
    .filter((s) => /^[A-Z]{3}$/.test(s))
    .slice(0, 6);
  if (!origins.length) return json({ items: [], updated_at: null });
  const rows = await db.select().from(schema.exploreCache).where(inArray(schema.exploreCache.origin, origins));
  return json({
    items: rows.flatMap((r) => r.items as unknown[]),
    updated_at: rows.map((r) => r.updatedAt).sort()[0] ?? null,
  });
});
