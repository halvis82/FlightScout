import { eq } from "drizzle-orm";
import { db, schema } from "@/lib/db";
import { json, requireUser, route, HttpError } from "@/lib/api";
import { emailConfigured, sendEmail } from "@/lib/notify";
import { testEmail } from "@/lib/email";
import { enforceRateLimit } from "@/lib/ratelimit";

// Settings, "Send a test email": the same delivery path a price alert takes.
export const POST = route(async (req) => {
  const userId = await requireUser(req);
  if (!emailConfigured()) throw new HttpError(503, "Email delivery has not been set up for FlightScout.");
  await enforceRateLimit(req, "email", userId);
  const [u] = await db.select().from(schema.user).where(eq(schema.user.id, userId));
  if (!u) throw new HttpError(404, "no such user");
  const ok = await sendEmail(u.email, testEmail(u)).catch(() => false);
  if (!ok) throw new HttpError(502, "The email could not be sent. Try again in a minute.");
  return json({ sent: true, to: u.email });
});
