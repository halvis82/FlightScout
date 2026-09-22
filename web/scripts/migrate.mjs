// Runs drizzle migrations when a database is configured. Used by `npm run build`
// (so Vercel deploys migrate first) and `npm run db:migrate`. Without
// DATABASE_URL it skips instead of failing, so local builds still work.
import { execSync } from "node:child_process";
import nextEnv from "@next/env";

nextEnv.loadEnvConfig(process.cwd());
const strict = process.argv.includes("--strict");

if (!process.env.DATABASE_URL) {
  const msg = "DATABASE_URL is not set, skipping migrations";
  if (strict) {
    console.error(msg);
    process.exit(1);
  }
  console.log(msg);
  process.exit(0);
}

execSync("npx drizzle-kit migrate", { stdio: "inherit", env: process.env });
