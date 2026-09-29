import { eq } from "drizzle-orm";
import { db, schema } from "@/lib/db";
import { body, json, requireUser, route, HttpError } from "@/lib/api";
import { emailConfigured } from "@/lib/notify";
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
  if (p.emailAlerts !== undefined && typeof p.emailAlerts !== "boolean") throw new HttpError(400, "emailAlerts must be a boolean");
  if (p.emailAlerts === true && !emailConfigured()) throw new HttpError(503, "Email delivery has not been set up for FlightScout.");
  const cur = await getSettings(userId);
  const [row] = await db
    .update(schema.settings)
    .set({
      currency: p.currency !== undefined ? cleanCurrency(p.currency) : cur.currency,
      defaultOrigins: p.defaultOrigins !== undefined ? cleanOrigins(p.defaultOrigins) : cur.defaultOrigins,
      planner: p.planner !== undefined ? cleanPlanner(p.planner, cur.planner) : cur.planner,
      sellerRules: p.sellerRules !== undefined ? cleanSellerRules(p.sellerRules) : cur.sellerRules,
      emailAlerts: p.emailAlerts !== undefined ? Boolean(p.emailAlerts) : cur.emailAlerts,
      pushAlerts: false,
      onboarded: p.onboarded !== undefined ? Boolean(p.onboarded) : cur.onboarded,
      updatedAt: new Date(),
    })
    .where(eq(schema.settings.userId, userId))
    .returning();
  return json(row);
});
