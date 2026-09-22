import { and, eq } from "drizzle-orm";
import { db, schema } from "@/lib/db";
import { body, json, requireUser, route, HttpError } from "@/lib/api";
import { sendPush } from "@/lib/notify";

type Sub = { endpoint: string; keys: { p256dh: string; auth: string } };

export const POST = route(async (req) => {
  const userId = await requireUser(req);
  const p = await body<{ subscription?: Sub; test?: boolean }>(req);
  if (p.test) {
    const n = await sendPush(userId, { title: "FlightScout", body: "Push alerts are working.", url: "/watches" });
    return json({ sent: n });
  }
  const s = p.subscription;
  if (!s?.endpoint || !s.keys?.p256dh || !s.keys?.auth) throw new HttpError(400, "bad subscription");
  await db
    .insert(schema.pushSubscriptions)
    .values({ userId, endpoint: s.endpoint, p256dh: s.keys.p256dh, auth: s.keys.auth })
    .onConflictDoUpdate({
      target: schema.pushSubscriptions.endpoint,
      set: { userId, p256dh: s.keys.p256dh, auth: s.keys.auth },
    });
  return json({ ok: true }, 201);
});

export const DELETE = route(async (req) => {
  const userId = await requireUser(req);
  const { endpoint } = await body<{ endpoint: string }>(req);
  await db
    .delete(schema.pushSubscriptions)
    .where(and(eq(schema.pushSubscriptions.userId, userId), eq(schema.pushSubscriptions.endpoint, endpoint)));
  return json({ ok: true });
});
