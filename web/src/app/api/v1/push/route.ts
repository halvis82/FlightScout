import { and, eq } from "drizzle-orm";
import { db, schema } from "@/lib/db";
import { body, json, requireUser, route, HttpError } from "@/lib/api";

// Older clients can remove their subscriptions, but cannot create or send push.
export const POST = route(async (req) => {
  await requireUser(req);
  throw new HttpError(410, "Push notifications have been retired. Use email alerts in Settings.");
});

export const DELETE = route(async (req) => {
  const userId = await requireUser(req);
  const { endpoint } = await body<{ endpoint: string }>(req);
  await db.delete(schema.pushSubscriptions)
    .where(and(eq(schema.pushSubscriptions.userId, userId), eq(schema.pushSubscriptions.endpoint, endpoint)));
  return json({ ok: true });
});
