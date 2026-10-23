import { eq } from "drizzle-orm";
import { db, schema } from "@/lib/db";
import { json, route, HttpError } from "@/lib/api";
import { checkUnsubscribe, siteUrl } from "@/lib/email";
import { getSettings } from "@/lib/settings";

// The signed link in every alert email. POST without signing in: Gmail's own
// one click button (RFC 8058) and the page at /unsubscribe. ?undo=1 turns
// alerts back on. A GET (someone opening the header link) goes to the page.
export const POST = route(async (req) => {
  const sp = new URL(req.url).searchParams;
  const userId = sp.get("u");
  if (!checkUnsubscribe(userId, sp.get("s"))) throw new HttpError(403, "This unsubscribe link is not valid.");
  await getSettings(userId!); // makes the row if it's missing
  const emailAlerts = sp.get("undo") === "1";
  await db.update(schema.settings).set({ emailAlerts, updatedAt: new Date() }).where(eq(schema.settings.userId, userId!));
  return json({ emailAlerts });
});

export const GET = route(async (req) => {
  return Response.redirect(siteUrl(`/unsubscribe${new URL(req.url).search}`), 303);
});
