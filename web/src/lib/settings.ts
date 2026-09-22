import "server-only";
import { eq } from "drizzle-orm";
import { db, schema } from "./db";
import { DEFAULT_PLANNER } from "./defaults";

export { DEFAULT_PLANNER };

export async function getSettings(userId: string) {
  const [row] = await db.select().from(schema.settings).where(eq(schema.settings.userId, userId));
  if (row) return { ...row, planner: { ...DEFAULT_PLANNER, ...(row.planner ?? {}) } };
  const [created] = await db
    .insert(schema.settings)
    .values({ userId, planner: DEFAULT_PLANNER })
    .onConflictDoNothing()
    .returning();
  if (created) return { ...created, planner: DEFAULT_PLANNER };
  const [again] = await db.select().from(schema.settings).where(eq(schema.settings.userId, userId));
  return { ...again, planner: { ...DEFAULT_PLANNER, ...(again.planner ?? {}) } };
}
