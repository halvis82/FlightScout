import { placeInput } from "@/lib/place-validate";
import { and, asc, eq } from "drizzle-orm";
import { db, schema } from "@/lib/db";
import { body, json, requireUser, route } from "@/lib/api";

export const GET = route(async (req) => {
  const userId = await requireUser(req);
  const rows = await db
    .select()
    .from(schema.places)
    .where(eq(schema.places.userId, userId))
    .orderBy(asc(schema.places.kind), asc(schema.places.label));
  return json(rows);
});

export const POST = route(async (req) => {
  const userId = await requireUser(req);
  const p = placeInput(await body<unknown>(req), false);
  const signature = p.signature!;
  const [row] = await db
    .insert(schema.places)
    .values({ userId, label: p.label!, codes: p.codes!, kind: p.kind!, color: p.color, notes: p.notes, signature })
    .onConflictDoNothing({ target: [schema.places.userId, schema.places.signature] })
    .returning();
  if (row) return json(row, 201);
  const [existing] = await db
    .select()
    .from(schema.places)
    .where(and(eq(schema.places.userId, userId), eq(schema.places.signature, signature)));
  return json({ ...existing, existing: true }, 200);
});
