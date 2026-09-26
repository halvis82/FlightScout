import { json, route } from "@/lib/api";

// Which commit is live for the website and the engine (the catch up deploy
// job compares these with main). Public: commit ids are public on GitHub.
export const GET = route(async () => {
  let engine: string | null = null;
  try {
    const base = process.env.ENGINE_URL;
    if (base) {
      const r = await fetch(base.replace(/\/$/, "") + "/health", { cache: "no-store", signal: AbortSignal.timeout(5000) });
      engine = ((await r.json()) as { commit?: string | null }).commit ?? null;
    }
  } catch {
    /* unknown */
  }
  return json({ web: process.env.VERCEL_GIT_COMMIT_SHA ?? null, engine }, { headers: { "Cache-Control": "no-store" } });
});
