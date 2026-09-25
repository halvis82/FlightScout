import "server-only";
import { drizzle as drizzlePg, type PostgresJsDatabase } from "drizzle-orm/postgres-js";
import postgres from "postgres";
import * as schema from "./schema";

export type DB = PostgresJsDatabase<typeof schema>;

const globalForDb = globalThis as unknown as { __fsDb?: DB };

function create(): DB {
  const url = process.env.DATABASE_URL;
  if (!url) throw new Error("DATABASE_URL is not set");
  if (url.startsWith("pglite:")) {
    // Local fallback without a Postgres server. Loaded lazily so production
    // bundles never pull in PGlite.
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { PGlite } = require("@electric-sql/pglite");
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { drizzle } = require("drizzle-orm/pglite");
    const dir = url.slice("pglite:".length) || "./.pglite";
    return drizzle(new PGlite(dir), { schema }) as unknown as DB;
  }
  const client = postgres(url, { prepare: false, max: process.env.VERCEL ? 1 : 5 });
  return drizzlePg(client, { schema });
}

// Opened on first use, not at import: build workers render pages that import
// this module without querying (and PGlite can't be opened by 9 at once).
function get(): DB {
  return globalForDb.__fsDb ?? (globalForDb.__fsDb = create());
}
export const db: DB = new Proxy({} as DB, {
  get: (_t, prop) => {
    const real = get() as unknown as Record<string | symbol, unknown>;
    const v = real[prop];
    return typeof v === "function" ? (v as (...a: unknown[]) => unknown).bind(real) : v;
  },
});
export { schema };
