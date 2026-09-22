import { desc, eq } from "drizzle-orm";
import { db, schema } from "@/lib/db";
import { body, json, newToken, requireUser, route } from "@/lib/api";

export const GET = route(async (req) => {
  const userId = await requireUser(req);
  const rows = await db
    .select({
      id: schema.apiTokens.id,
      name: schema.apiTokens.name,
      prefix: schema.apiTokens.prefix,
      created_at: schema.apiTokens.createdAt,
      last_used_at: schema.apiTokens.lastUsedAt,
    })
    .from(schema.apiTokens)
    .where(eq(schema.apiTokens.userId, userId))
    .orderBy(desc(schema.apiTokens.createdAt));
  return json(rows);
});

// The raw token is returned once and never stored.
export const POST = route(async (req) => {
  const userId = await requireUser(req);
  const { name } = await body<{ name?: string }>(req);
  const t = newToken();
  const [row] = await db
    .insert(schema.apiTokens)
    .values({ userId, name: (name || "CLI").slice(0, 60), tokenHash: t.hash, prefix: t.prefix })
    .returning({ id: schema.apiTokens.id, name: schema.apiTokens.name, prefix: schema.apiTokens.prefix });
  return json({ ...row, token: t.raw }, 201);
});
