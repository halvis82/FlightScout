import "server-only";
import { and, eq } from "drizzle-orm";
import { db, schema } from "./db";
import { HttpError } from "./api";

export async function ownWatch(userId: string, id: number) {
  const [w] = await db
    .select()
    .from(schema.watches)
    .where(and(eq(schema.watches.id, id), eq(schema.watches.userId, userId)));
  if (!w) throw new HttpError(404, "watch not found");
  return w;
}
