import { defineConfig } from "drizzle-kit";

const url = process.env.DATABASE_URL ?? "";

export default url.startsWith("pglite:")
  ? defineConfig({
      schema: "./src/lib/db/schema.ts",
      out: "./drizzle",
      dialect: "postgresql",
      driver: "pglite",
      dbCredentials: { url: url.slice("pglite:".length) || "./.pglite" },
    })
  : defineConfig({
      schema: "./src/lib/db/schema.ts",
      out: "./drizzle",
      dialect: "postgresql",
      dbCredentials: { url },
    });
