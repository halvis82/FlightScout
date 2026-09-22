import { eq } from "drizzle-orm";
import { db, schema } from "@/lib/db";
import { body, json, requireUser, route, HttpError } from "@/lib/api";
import { getSettings } from "@/lib/settings";
import { CURRENCIES } from "@/lib/types";
import type { PlannerDefaults, SellerRule } from "@/lib/db/schema";

type Patch = Partial<{
  currency: string;
  defaultOrigins: string[];
  planner: Partial<PlannerDefaults>;
  sellerRules: SellerRule[];
  emailAlerts: boolean;
  pushAlerts: boolean;
  onboarded: boolean;
}>;

export const PATCH = route(async (req) => {
  const userId = await requireUser(req);
  const p = await body<Patch>(req);
  const cur = await getSettings(userId);
  if (p.currency && !(CURRENCIES as readonly string[]).includes(p.currency))
    throw new HttpError(400, "unsupported currency");
  const [row] = await db
    .update(schema.settings)
    .set({
      currency: p.currency ?? cur.currency,
      defaultOrigins: p.defaultOrigins?.map((c) => c.toUpperCase()) ?? cur.defaultOrigins,
      planner: p.planner ? { ...cur.planner, ...p.planner } : cur.planner,
      sellerRules: p.sellerRules ?? cur.sellerRules,
      emailAlerts: p.emailAlerts ?? cur.emailAlerts,
      pushAlerts: p.pushAlerts ?? cur.pushAlerts,
      onboarded: p.onboarded ?? cur.onboarded,
      updatedAt: new Date(),
    })
    .where(eq(schema.settings.userId, userId))
    .returning();
  return json(row);
});
