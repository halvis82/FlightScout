import { eq } from "drizzle-orm";
import { db, schema } from "@/lib/db";
import { body, intParam, json, requireUser, route } from "@/lib/api";
import { toColumns, type WatchIn } from "@/lib/watch-validate";
import { ownWatch } from "@/lib/watches";

type Ctx = { params: Promise<{ id: string }> };

export const GET = route<Ctx>(async (req, { params }) => {
  const userId = await requireUser(req);
  return json(await ownWatch(userId, intParam((await params).id)));
});

export const PATCH = route<Ctx>(async (req, { params }) => {
  const userId = await requireUser(req);
  const id = intParam((await params).id);
  await ownWatch(userId, id);
  const cols = toColumns(await body<WatchIn>(req), true);
  const [row] = await db.update(schema.watches).set(cols).where(eq(schema.watches.id, id)).returning();
  return json(row);
});

export const DELETE = route<Ctx>(async (req, { params }) => {
  const userId = await requireUser(req);
  const id = intParam((await params).id);
  await ownWatch(userId, id);
  await db.delete(schema.watches).where(eq(schema.watches.id, id));
  return json({ ok: true });
});
