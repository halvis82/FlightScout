import { and, eq } from "drizzle-orm";
import { db, schema } from "@/lib/db";
import { body, intParam, json, requireUser, route, HttpError } from "@/lib/api";
import { extendSearch } from "@/lib/searches";
import type { Trip } from "@/lib/types";

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

// The whole streamed result, once every part is in (the first part was saved
// when it arrived).
export const PATCH = route<Ctx>(async (req, { params }) => {
  const userId = await requireUser(req);
  const id = intParam((await params).id);
  const p = await body<{ payload: { trips?: Trip[] } }>(req);
  const saved = await extendSearch(userId, id, p.payload);
  if (!saved) throw new HttpError(404, "not found");
  return json(saved);
});

export const DELETE = route<Ctx>(async (req, { params }) => {
  const userId = await requireUser(req);
  const id = intParam((await params).id);
  await db.delete(schema.searches).where(and(eq(schema.searches.id, id), eq(schema.searches.userId, userId)));
  return json({ ok: true });
});
