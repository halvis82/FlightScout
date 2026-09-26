import { eq } from "drizzle-orm";
import { db, schema } from "@/lib/db";
import { body, HttpError, intParam, json, requireUser, route } from "@/lib/api";
import { watchSignature } from "@/lib/signature";
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
  const cur = await ownWatch(userId, id);
  const cols = toColumns(await body<WatchIn>(req), true) as Partial<typeof schema.watches.$inferInsert>;
  const next = { ...cur, ...cols };
  // a one way watch has no trip length; its identity follows the edit
  if (next.tripType === "oneway") cols.nightsMin = cols.nightsMax = next.nightsMin = next.nightsMax = null;
  const signature = watchSignature({ ...next, departStart: String(next.departStart), departEnd: next.departEnd ? String(next.departEnd) : null });
  const mine = await db.select().from(schema.watches).where(eq(schema.watches.userId, userId));
  if (mine.some((w) => w.id !== id && w.signature === signature)) throw new HttpError(409, "You already watch exactly this search.");
  const [row] = await db.update(schema.watches).set({ ...cols, signature }).where(eq(schema.watches.id, id)).returning();
  return json(row);
});

export const DELETE = route<Ctx>(async (req, { params }) => {
  const userId = await requireUser(req);
  const id = intParam((await params).id);
  await ownWatch(userId, id);
  await db.delete(schema.watches).where(eq(schema.watches.id, id));
  return json({ ok: true });
});
