import "server-only";
import { eq } from "drizzle-orm";
import { db, schema } from "./db";
import { DEFAULT_PLANNER } from "./defaults";
import { cleanPlanner, cleanSellerRules } from "./settings-validate";

export { DEFAULT_PLANNER };

// Whatever is stored, what the app gets is always usable.
function usable<T extends { planner: unknown; sellerRules: unknown; defaultOrigins: unknown }>(row: T) {
  return {
    ...row,
    planner: (() => {
      try {
        return cleanPlanner(row.planner ?? {});
      } catch {
        return DEFAULT_PLANNER; // an unusable stored value: start from the defaults
      }
    })(),
    sellerRules: cleanSellerRules(row.sellerRules, false),
    defaultOrigins: Array.isArray(row.defaultOrigins) ? (row.defaultOrigins as string[]) : [],
  };
}

export async function getSettings(userId: string) {
  const [row] = await db.select().from(schema.settings).where(eq(schema.settings.userId, userId));
  if (row) return usable(row);
  const [created] = await db
    .insert(schema.settings)
    .values({ userId, planner: DEFAULT_PLANNER })
    .onConflictDoNothing()
    .returning();
  if (created) return { ...created, planner: DEFAULT_PLANNER };
  const [again] = await db.select().from(schema.settings).where(eq(schema.settings.userId, userId));
  return usable(again);
}
