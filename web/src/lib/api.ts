import "server-only";
import { createHash, randomBytes, timingSafeEqual } from "crypto";
import { headers } from "next/headers";
import { NextResponse } from "next/server";
import { eq } from "drizzle-orm";
import { auth } from "./auth";
import { db, schema } from "./db";

export class HttpError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export function json(data: unknown, init?: number | ResponseInit) {
  return NextResponse.json(data, typeof init === "number" ? { status: init } : init);
}

export function hashToken(token: string) {
  return createHash("sha256").update(token).digest("hex");
}

export function newToken() {
  const raw = "fsk_" + randomBytes(24).toString("base64url");
  return { raw, hash: hashToken(raw), prefix: raw.slice(0, 10) };
}

// Like requireUser, but returns null for anonymous (guest) callers. A bad
// bearer token is still an error.
export async function optionalUser(req: Request): Promise<string | null> {
  try {
    return await requireUser(req);
  } catch (e) {
    if (e instanceof HttpError && e.status === 401 && !req.headers.get("authorization")) return null;
    throw e;
  }
}

// Resolve the caller: a browser session cookie or a `Bearer fsk_...` API token.
export async function requireUser(req?: Request): Promise<string> {
  const h = req ? req.headers : await headers();
  const authz = h.get("authorization");
  if (authz?.startsWith("Bearer ")) {
    const token = authz.slice(7).trim();
    const [row] = await db
      .select()
      .from(schema.apiTokens)
      .where(eq(schema.apiTokens.tokenHash, hashToken(token)))
      .limit(1);
    if (!row) throw new HttpError(401, "invalid API token");
    // best effort bookkeeping
    db.update(schema.apiTokens)
      .set({ lastUsedAt: new Date() })
      .where(eq(schema.apiTokens.id, row.id))
      .catch(() => {});
    return row.userId;
  }
  const session = await auth.api.getSession({ headers: h });
  if (!session) throw new HttpError(401, "not signed in");
  return session.user.id;
}

export function requireTracker(req: Request) {
  const key = process.env.TRACKER_KEY;
  const got = req.headers.get("x-tracker-key") ?? "";
  if (!key) throw new HttpError(503, "TRACKER_KEY is not configured");
  const a = Buffer.from(key);
  const b = Buffer.from(got);
  if (a.length !== b.length || !timingSafeEqual(a, b)) throw new HttpError(401, "bad tracker key");
}

type Handler<C> = (req: Request, ctx: C) => Promise<Response>;

// Wrap a route handler so thrown HttpErrors (and anything else) become JSON.
export function route<C = unknown>(fn: Handler<C>): Handler<C> {
  return async (req, ctx) => {
    try {
      return await fn(req, ctx);
    } catch (e) {
      if (e instanceof HttpError) return json({ error: e.message }, e.status);
      console.error(e);
      return json({ error: e instanceof Error ? e.message : "internal error" }, 500);
    }
  };
}

export async function body<T>(req: Request): Promise<T> {
  try {
    return (await req.json()) as T;
  } catch {
    throw new HttpError(400, "invalid JSON body");
  }
}

export function intParam(v: string) {
  const n = Number(v);
  if (!Number.isInteger(n)) throw new HttpError(400, "bad id");
  return n;
}
