import { eq } from "drizzle-orm";
import { db, schema } from "@/lib/db";
import { body, json, requireUser, route, HttpError } from "@/lib/api";
import { getSettings } from "@/lib/settings";
import { cleanCurrency, cleanOrigins, cleanPlanner, cleanSellerRules } from "@/lib/settings-validate";
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
  if (!p || typeof p !== "object") throw new HttpError(400, "expected a JSON object");
  const cur = await getSettings(userId);
  const [row] = await db
    .update(schema.settings)
    .set({
      currency: p.currency !== undefined ? cleanCurrency(p.currency) : cur.currency,
      defaultOrigins: p.defaultOrigins !== undefined ? cleanOrigins(p.defaultOrigins) : cur.defaultOrigins,
      planner: p.planner !== undefined ? cleanPlanner(p.planner, cur.planner) : cur.planner,
      sellerRules: p.sellerRules !== undefined ? cleanSellerRules(p.sellerRules) : cur.sellerRules,
      emailAlerts: p.emailAlerts !== undefined ? Boolean(p.emailAlerts) : cur.emailAlerts,
      pushAlerts: p.pushAlerts !== undefined ? Boolean(p.pushAlerts) : cur.pushAlerts,
      onboarded: p.onboarded !== undefined ? Boolean(p.onboarded) : cur.onboarded,
      updatedAt: new Date(),
    })
    .where(eq(schema.settings.userId, userId))
    .returning();
  return json(row);
});
