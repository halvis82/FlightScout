import { and, eq } from "drizzle-orm";
import { db, schema } from "@/lib/db";
import { intParam, json, requireUser, route } from "@/lib/api";

type Ctx = { params: Promise<{ id: string }> };

export const DELETE = route<Ctx>(async (req, { params }) => {
  const userId = await requireUser(req);
  const id = intParam((await params).id);
  await db.delete(schema.apiTokens).where(and(eq(schema.apiTokens.id, id), eq(schema.apiTokens.userId, userId)));
  return json({ ok: true });
});
