import "server-only";
import { json, optionalUser } from "./api";
import { engine } from "./engine";
import { enforceRateLimit, type EngineKind } from "./ratelimit";
import { saveSearch } from "./searches";
import { cacheGet, cacheKey, cachePut } from "./search-cache";
import { getSettings } from "./settings";
import type { SellerRule } from "./db/schema";

// Engine endpoints that return lists get wrapped as {items, errors}.
function normalize(kind: EngineKind, raw: unknown): Record<string, unknown> {
  if (Array.isArray(raw)) return { items: raw, errors: {} };
  const r = raw as Record<string, unknown>;
  if (kind === "explore" && Array.isArray(r.destinations)) return { items: r.destinations, errors: r.errors ?? {} };
  return r;
}

function rulesToEngine(rules: SellerRule[]) {
  return Object.fromEntries(rules.map((r) => [r.seller, r.mode]));
}

// Shared handler for /api/v1/{search,plan,explore,dates,trip}. Works for
// guests (rate limited per IP) and signed in users (saved to history, feeds
// matching watches).
export async function proxyEngine(req: Request, kind: EngineKind) {
  const userId = await optionalUser(req);
  const q = (await req.json().catch(() => ({}))) as Record<string, unknown>;
  // Streamed searches send several parts; only the first counts toward rate
  // limits and gets saved to history (it also feeds matching watches).
  const part = typeof q.part === "number" ? q.part : 0;
  delete q.part;
  const followUp = (kind === "explore" && typeof q.batch === "number" && q.batch > 0) || part > 0;
  // `quiet` requests (calendar prices, date strips) are not saved to history
  const quiet = q.quiet === true || part > 0;
  delete q.quiet;
  const payload = { ...q };
  if ((kind === "search" || kind === "plan") && !payload.seller_rules) {
    // guests send their rules inline; signed in users use saved settings
    const rules = Array.isArray(q.sellerRules)
      ? (q.sellerRules as SellerRule[])
      : userId
        ? (await getSettings(userId)).sellerRules
        : [];
    const blocked = rules.filter((r) => r.mode === "block");
    if (blocked.length) payload.seller_rules = rulesToEngine(blocked);
  }
  delete payload.sellerRules;
  // Shared cache: the same search (by anyone) within a few minutes is served
  // without asking the sources again, and doesn't count toward rate limits.
  const key = cacheKey(kind, payload);
  let result = await cacheGet(kind, key);
  if (!result) {
    await enforceRateLimit(req, kind, userId, followUp);
    result = normalize(kind, await engine<unknown>(kind === "browser" ? "/google/browser" : `/${kind}`, payload));
    const errs = (result as { errors?: Record<string, string> }).errors ?? {};
    const trips = (result as { trips?: unknown[]; items?: unknown[] }).trips ?? (result as { items?: unknown[] }).items;
    // only cache complete, useful answers ("paused" and "still searching"
    // notes are expected and don't make an answer incomplete)
    const hard = Object.values(errs).filter((m) => !/^(paused for|still searching)/.test(String(m)));
    if (!hard.length && (!Array.isArray(trips) || trips.length)) await cachePut(kind, key, result);
  }
  // browser mode: "need more pages" answers are just passed through
  if ((result as { need?: unknown }).need) return json(result);
  if (!userId || quiet) return json({ ...result, search_id: null, watches_updated: 0 });
  delete q.pages;
  const saved = await saveSearch(userId, kind === "browser" ? "search" : kind, "web", q, result);
  return json({ ...result, search_id: saved.id, watches_updated: saved.watchesUpdated });
}
