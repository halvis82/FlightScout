import { and, eq } from "drizzle-orm";
import { db, schema } from "@/lib/db";
import { body, intParam, json, requireUser, route } from "@/lib/api";

type Ctx = { params: Promise<{ id: string }> };

export const PATCH = route<Ctx>(async (req, { params }) => {
  const userId = await requireUser(req);
  const id = intParam((await params).id);
  const p = await body<Partial<{ label: string; codes: string[]; kind: "home" | "frequent" | "interested"; color: string; notes: string }>>(req);
  const [row] = await db
    .update(schema.places)
    .set({ ...p, codes: p.codes?.map((c) => c.toUpperCase()) })
    .where(and(eq(schema.places.id, id), eq(schema.places.userId, userId)))
    .returning();
  return json(row ?? { error: "not found" }, row ? 200 : 404);
});

export const DELETE = route<Ctx>(async (req, { params }) => {
  const userId = await requireUser(req);
  const id = intParam((await params).id);
  await db.delete(schema.places).where(and(eq(schema.places.id, id), eq(schema.places.userId, userId)));
  return json({ ok: true });
});
