import { eq } from "drizzle-orm";
import { db, schema } from "@/lib/db";
import { body, HttpError, intParam, json, requireUser, route } from "@/lib/api";
import { watchSignature } from "@/lib/signature";
import { checkWatch, toColumns, type WatchIn } from "@/lib/watch-validate";
import { convertWith, getRates } from "@/lib/fx";
import { ownWatch } from "@/lib/watches";
import { alertIfTargetMet } from "@/lib/observations";

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
  checkWatch({ ...next, departStart: String(next.departStart), departEnd: String(next.departEnd) });
  const signature = watchSignature({ ...next, departStart: String(next.departStart), departEnd: next.departEnd ? String(next.departEnd) : null });
  const oldSignature = watchSignature({ ...cur, departStart: String(cur.departStart), departEnd: cur.departEnd ? String(cur.departEnd) : null });
  if (signature !== oldSignature || next.currency !== cur.currency) {
    // another search now: earlier prices no longer describe it
    Object.assign(cols, { pricesSince: new Date(), bestPrice: null, prevPrice: null, lowestPrice: null, bestTrip: null });
    // a target in the old currency, converted (unless a new one came with the edit)
    if (next.currency !== cur.currency && cols.alertBelow === undefined && cur.alertBelow != null) {
      cols.alertBelow = Math.round(convertWith(await getRates(), cur.alertBelow, cur.currency, next.currency));
    }
  }
  const mine = await db.select().from(schema.watches).where(eq(schema.watches.userId, userId));
  if (mine.some((w) => w.id !== id && w.signature === signature)) throw new HttpError(409, "You already watch exactly this search.");
  const [row] = await db.update(schema.watches).set({ ...cols, signature }).where(eq(schema.watches.id, id)).returning();
  await alertIfTargetMet(cur, row);
  return json(row);
});

export const DELETE = route<Ctx>(async (req, { params }) => {
  const userId = await requireUser(req);
  const id = intParam((await params).id);
  await ownWatch(userId, id);
  await db.delete(schema.watches).where(eq(schema.watches.id, id));
  return json({ ok: true });
});
