import { eq } from "drizzle-orm";
import { db, schema } from "@/lib/db";
import { body, json, requireTracker, route, HttpError } from "@/lib/api";
import { recordObservations, type ObservationInput } from "@/lib/observations";

type In = { watch_id: number; observations: ObservationInput[]; errors?: Record<string, string> };

export const POST = route(async (req) => {
  requireTracker(req);
  const p = await body<In>(req);
  const [w] = await db.select().from(schema.watches).where(eq(schema.watches.id, Number(p.watch_id)));
  if (!w) throw new HttpError(404, "watch not found");
  if (!Array.isArray(p.observations)) throw new HttpError(400, "observations must be an array");
  if (!p.observations.length) {
    await db.update(schema.watches).set({ lastCheckedAt: new Date() }).where(eq(schema.watches.id, w.id));
    return json({ inserted: 0, alerts: 0 });
  }
  return json(await recordObservations(w, p.observations), 201);
});
