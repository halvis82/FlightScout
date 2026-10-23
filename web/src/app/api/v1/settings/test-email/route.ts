import { eq } from "drizzle-orm";
import { db, schema } from "@/lib/db";
import { json, requireUser, route, HttpError } from "@/lib/api";
import { emailConfigured, sendEmail } from "@/lib/notify";
import { enforceRateLimit } from "@/lib/ratelimit";

// Settings, "Send a test email": the same delivery path a price alert takes.
export const POST = route(async (req) => {
  const userId = await requireUser(req);
  if (!emailConfigured()) throw new HttpError(503, "Email delivery has not been set up for FlightScout.");
  await enforceRateLimit(req, "email", userId);
  const [u] = await db.select().from(schema.user).where(eq(schema.user.id, userId));
  if (!u) throw new HttpError(404, "no such user");
  const base = process.env.BETTER_AUTH_URL ?? "";
  const ok = await sendEmail(
    u.email,
    "FlightScout test email",
    `<p>Email alerts work. FlightScout will email you here when a watched flight reaches its target price or drops by its percentage.</p><p><a href="${base}/watches">Your watchlist</a></p>`,
  ).catch(() => false);
  if (!ok) throw new HttpError(502, "The email could not be sent. Try again in a minute.");
  return json({ sent: true, to: u.email });
});
