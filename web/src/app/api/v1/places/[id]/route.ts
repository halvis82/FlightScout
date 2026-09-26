import { and, eq } from "drizzle-orm";
import { db, schema } from "@/lib/db";
import { body, intParam, json, requireUser, route } from "@/lib/api";
import { placeSignature } from "@/lib/signature";

// "Start searches from" holds a copy of a favorite's codes: keep it in step
// when that favorite changes or goes away.
async function syncDefault(userId: string, oldCodes: string[], newCodes: string[]) {
  const [s] = await db.select().from(schema.settings).where(eq(schema.settings.userId, userId));
  if (!s?.defaultOrigins.length || placeSignature(s.defaultOrigins) !== placeSignature(oldCodes)) return;
  await db.update(schema.settings).set({ defaultOrigins: newCodes }).where(eq(schema.settings.userId, userId));
}

type Ctx = { params: Promise<{ id: string }> };

export const PATCH = route<Ctx>(async (req, { params }) => {
  const userId = await requireUser(req);
  const id = intParam((await params).id);
  const [prev] = await db.select().from(schema.places).where(and(eq(schema.places.id, id), eq(schema.places.userId, userId)));
  const p = await body<Partial<{ label: string; codes: string[]; kind: "home" | "frequent" | "interested"; color: string; notes: string }>>(req);
  const [row] = await db
    .update(schema.places)
    .set({ ...p, codes: p.codes?.map((c) => c.toUpperCase()) })
    .where(and(eq(schema.places.id, id), eq(schema.places.userId, userId)))
    .returning();
  if (prev && row && p.codes) await syncDefault(userId, prev.codes, row.codes);
  return json(row ?? { error: "not found" }, row ? 200 : 404);
});

export const DELETE = route<Ctx>(async (req, { params }) => {
  const userId = await requireUser(req);
  const id = intParam((await params).id);
  const [gone] = await db.delete(schema.places).where(and(eq(schema.places.id, id), eq(schema.places.userId, userId))).returning();
  if (gone) await syncDefault(userId, gone.codes, []);
  return json({ ok: true });
});
