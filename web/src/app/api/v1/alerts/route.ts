import { and, desc, eq, isNull } from "drizzle-orm";
import { db, schema } from "@/lib/db";
import { body, json, requireUser, route } from "@/lib/api";

export const GET = route(async (req) => {
  const userId = await requireUser(req);
  const rows = await db
    .select()
    .from(schema.alerts)
    .where(eq(schema.alerts.userId, userId))
    .orderBy(desc(schema.alerts.createdAt))
    .limit(50);
  return json({ alerts: rows, unread: rows.filter((r) => !r.readAt).length });
});

// Mark alerts read: {ids: number[]} or {all: true}
export const POST = route(async (req) => {
  const userId = await requireUser(req);
  const p = await body<{ ids?: number[]; all?: boolean }>(req);
  const now = new Date();
  if (p.all) {
    await db
      .update(schema.alerts)
      .set({ readAt: now })
      .where(and(eq(schema.alerts.userId, userId), isNull(schema.alerts.readAt)));
  } else {
    for (const id of p.ids ?? []) {
      await db
        .update(schema.alerts)
        .set({ readAt: now })
        .where(and(eq(schema.alerts.userId, userId), eq(schema.alerts.id, id)));
    }
  }
  return json({ ok: true });
});
