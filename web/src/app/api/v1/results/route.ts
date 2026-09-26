import { body, json, requireUser, route, HttpError } from "@/lib/api";
import { saveSearch } from "@/lib/searches";
import { recordFares } from "@/lib/fares";
import type { Trip } from "@/lib/types";

type In = {
  kind: "search" | "plan" | "explore" | "dates" | "trip" | "multicity";
  query: Record<string, unknown>;
  payload: unknown;
  origin?: "web" | "cli" | "mcp" | "local";
};

// Results found elsewhere (CLI, MCP, agents, the browser's local runner) pushed
// into the user's history. Search and plan results also feed matching watches.
export const POST = route(async (req) => {
  const userId = await requireUser(req);
  const p = await body<In>(req);
  if (!["search", "plan", "explore", "dates", "trip", "multicity"].includes(p.kind)) throw new HttpError(400, "bad kind");
  if (!p.query || typeof p.query !== "object") throw new HttpError(400, "query is required");
  const payload = Array.isArray(p.payload) ? { items: p.payload } : p.payload;
  const origin = ["web", "cli", "mcp", "local"].includes(p.origin ?? "") ? p.origin! : "cli";
  const saved = await saveSearch(userId, p.kind, origin, p.query, payload);
  if (p.kind === "search" || p.kind === "plan") await recordFares((payload as { trips?: Trip[] } | null)?.trips);
  const base = process.env.BETTER_AUTH_URL ?? new URL(req.url).origin;
  return json({ ...saved, url: `${base}/history/${saved.id}` }, 201);
});
