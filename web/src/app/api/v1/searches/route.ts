import { and, desc, eq, lt } from "drizzle-orm";
import { db, schema } from "@/lib/db";
import { json, requireUser, route } from "@/lib/api";

// History list without payloads. ?before=<id> pages backwards, ?limit=N.
export const GET = route(async (req) => {
  const userId = await requireUser(req);
  const sp = new URL(req.url).searchParams;
  const limit = Math.min(200, Number(sp.get("limit") ?? 50));
  const before = sp.get("before");
  const rows = await db
    .select({
      id: schema.searches.id,
      kind: schema.searches.kind,
      origin: schema.searches.origin,
      summary: schema.searches.summary,
      query: schema.searches.query,
      created_at: schema.searches.createdAt,
    })
    .from(schema.searches)
    .where(
      before
        ? and(eq(schema.searches.userId, userId), lt(schema.searches.id, Number(before)))
        : eq(schema.searches.userId, userId),
    )
    .orderBy(desc(schema.searches.id))
    .limit(limit);
  return json(rows);
});
