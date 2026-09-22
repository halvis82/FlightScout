import { asc, eq } from "drizzle-orm";
import { db, schema } from "@/lib/db";
import { body, json, requireUser, route, HttpError } from "@/lib/api";

export const GET = route(async (req) => {
  const userId = await requireUser(req);
  const rows = await db
    .select()
    .from(schema.places)
    .where(eq(schema.places.userId, userId))
    .orderBy(asc(schema.places.kind), asc(schema.places.label));
  return json(rows);
});

type In = { label: string; codes: string[] | string; kind?: "home" | "frequent" | "interested"; color?: string; notes?: string };

export const POST = route(async (req) => {
  const userId = await requireUser(req);
  const p = await body<In>(req);
  const codes = (Array.isArray(p.codes) ? p.codes : p.codes.split(","))
    .map((c) => c.trim().toUpperCase())
    .filter((c) => /^[A-Z]{3,4}$/.test(c));
  if (!p.label?.trim() || !codes.length) throw new HttpError(400, "label and at least one airport code are required");
  const [row] = await db
    .insert(schema.places)
    .values({ userId, label: p.label.trim(), codes, kind: p.kind ?? "frequent", color: p.color, notes: p.notes })
    .returning();
  return json(row, 201);
});
