import { body, json, requireUser, route, HttpError } from "@/lib/api";
import { saveSearch } from "@/lib/searches";

type In = {
  kind: "search" | "plan" | "explore" | "dates" | "trip";
  query: Record<string, unknown>;
  payload: unknown;
  origin?: "web" | "cli" | "mcp";
};

// Results found elsewhere (CLI, MCP, agents) pushed into the user's history.
export const POST = route(async (req) => {
  const userId = await requireUser(req);
  const p = await body<In>(req);
  if (!["search", "plan", "explore", "dates", "trip"].includes(p.kind)) throw new HttpError(400, "bad kind");
  if (!p.query || typeof p.query !== "object") throw new HttpError(400, "query is required");
  const payload = Array.isArray(p.payload) ? { items: p.payload } : p.payload;
  const saved = await saveSearch(userId, p.kind, p.origin ?? "cli", p.query, payload);
  const base = process.env.BETTER_AUTH_URL ?? new URL(req.url).origin;
  return json({ ...saved, url: `${base}/history/${saved.id}` }, 201);
});
