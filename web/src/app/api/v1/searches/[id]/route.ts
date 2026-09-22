import { and, eq } from "drizzle-orm";
import { db, schema } from "@/lib/db";
import { intParam, json, requireUser, route, HttpError } from "@/lib/api";

type Ctx = { params: Promise<{ id: string }> };

export const GET = route<Ctx>(async (req, { params }) => {
  const userId = await requireUser(req);
  const id = intParam((await params).id);
  const [row] = await db
    .select()
    .from(schema.searches)
    .where(and(eq(schema.searches.id, id), eq(schema.searches.userId, userId)));
  if (!row) throw new HttpError(404, "not found");
  return json(row);
});

export const DELETE = route<Ctx>(async (req, { params }) => {
  const userId = await requireUser(req);
  const id = intParam((await params).id);
  await db.delete(schema.searches).where(and(eq(schema.searches.id, id), eq(schema.searches.userId, userId)));
  return json({ ok: true });
});
