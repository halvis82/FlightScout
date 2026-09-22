import { eq } from "drizzle-orm";
import { db, schema } from "@/lib/db";
import { json, optionalUser, route } from "@/lib/api";
import { getSettings } from "@/lib/settings";
import { emailConfigured, pushConfigured } from "@/lib/notify";
import { enabledSocialProviders } from "@/lib/auth";

// Guests get {user: null}; the client then keeps their data in localStorage.
export const GET = route(async (req) => {
  const features = {
    push: pushConfigured(),
    email: emailConfigured(),
    engine: Boolean(process.env.ENGINE_URL),
    oauth: enabledSocialProviders,
  };
  const userId = await optionalUser(req);
  if (!userId) return json({ user: null, settings: null, features });
  const [u] = await db
    .select({ id: schema.user.id, name: schema.user.name, email: schema.user.email })
    .from(schema.user)
    .where(eq(schema.user.id, userId));
  if (!u) return json({ user: null, settings: null, features });
  return json({ user: u, settings: await getSettings(userId), features });
});
