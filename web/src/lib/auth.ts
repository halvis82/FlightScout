import "server-only";
import { betterAuth } from "better-auth";
import { APIError } from "better-auth/api";
import { drizzleAdapter } from "better-auth/adapters/drizzle";
import { nextCookies } from "better-auth/next-js";
import { passkey } from "@better-auth/passkey";
import { db, schema } from "./db";

const baseURL =
  process.env.BETTER_AUTH_URL ??
  (process.env.VERCEL_PROJECT_PRODUCTION_URL
    ? `https://${process.env.VERCEL_PROJECT_PRODUCTION_URL}`
    : "http://localhost:3000");

const socialProviders: Record<string, { clientId: string; clientSecret: string }> = {};
if (process.env.GITHUB_CLIENT_ID && process.env.GITHUB_CLIENT_SECRET) {
  socialProviders.github = {
    clientId: process.env.GITHUB_CLIENT_ID,
    clientSecret: process.env.GITHUB_CLIENT_SECRET,
  };
}
if (process.env.GOOGLE_CLIENT_ID && process.env.GOOGLE_CLIENT_SECRET) {
  socialProviders.google = {
    clientId: process.env.GOOGLE_CLIENT_ID,
    clientSecret: process.env.GOOGLE_CLIENT_SECRET,
  };
}

// Only these emails may create accounts. Everyone else can still use the site
// as a guest.
export const allowedSignupEmails = (process.env.ALLOWED_SIGNUP_EMAILS ?? "hhafnor@gmail.com")
  .split(",")
  .map((e) => e.trim().toLowerCase())
  .filter(Boolean);

export const INVITE_ONLY_MESSAGE =
  "Sign ups are invite only for now. You can keep using FlightScout as a guest: search, smart routes, explore and a local watchlist all work without an account.";

export const auth = betterAuth({
  baseURL,
  secret: process.env.BETTER_AUTH_SECRET,
  database: drizzleAdapter(db, {
    provider: "pg",
    schema: {
      user: schema.user,
      session: schema.session,
      account: schema.account,
      verification: schema.verification,
      passkey: schema.passkey,
    },
  }),
  emailAndPassword: { enabled: true, minPasswordLength: 8 },
  socialProviders,
  session: { expiresIn: 60 * 60 * 24 * 60, updateAge: 60 * 60 * 24 },
  trustedOrigins: [baseURL, "https://flightscout-app.vercel.app"],
  databaseHooks: {
    user: {
      create: {
        // Enforced for every sign up path (email, OAuth, passkey).
        before: async (user) => {
          if (!allowedSignupEmails.includes(String(user.email ?? "").toLowerCase())) {
            throw new APIError("FORBIDDEN", { message: INVITE_ONLY_MESSAGE });
          }
          return { data: user };
        },
      },
    },
  },
  plugins: [
    passkey({
      rpID: new URL(baseURL).hostname,
      rpName: "FlightScout",
      origin: baseURL,
    }),
    nextCookies(),
  ],
});

export const enabledSocialProviders = Object.keys(socialProviders);
