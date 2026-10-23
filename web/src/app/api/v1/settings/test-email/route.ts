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
    "FlightScout: your email alerts are working",
    `<p>Hi,</p><p>This is the test email you asked for in FlightScout Settings. Email alerts are working.</p><p>From now on FlightScout will write to you here when a flight on your watchlist reaches its target price or drops by the percentage you set. Prices are checked twice a day, and each watch emails at most once every 12 hours.</p><p><a href="${base}/watches">Open your watchlist</a></p>`,
  ).catch(() => false);
  if (!ok) throw new HttpError(502, "The email could not be sent. Try again in a minute.");
  return json({ sent: true, to: u.email });
});
