import { DEFAULT_PLANNER } from "./defaults";
import { HttpError } from "./http-error";
import { CURRENCIES } from "./types";
import type { PlannerDefaults, SellerRule } from "./db/schema";

// Settings input, checked the same way for accounts (API) and guests (browser).
// Unknown keys are dropped and numbers clamped, so a stored value can never
// break searches, watch checks or the Settings page.

const LIMITS: Record<keyof PlannerDefaults, [number, number] | "bool" | "days"> = {
  max_stopover_days: [0, 30],
  min_connection_hours: [0.5, 24],
  max_trip_days: "days",
  max_hubs: [1, 30],
  allow_self_transfer: "bool",
  include_nested_roundtrips: "bool",
};

// A clean planner from anything (stored or sent), on top of the defaults.
export function cleanPlanner(p: unknown, base: PlannerDefaults = DEFAULT_PLANNER): PlannerDefaults {
  const out: PlannerDefaults = { ...DEFAULT_PLANNER, ...pickPlanner(base) };
  if (!p || typeof p !== "object") return out;
  const b = p as Record<string, unknown>;
  for (const [k, rule] of Object.entries(LIMITS) as [keyof PlannerDefaults, (typeof LIMITS)[keyof PlannerDefaults]][]) {
    if (!(k in b)) continue;
    const v = b[k];
    if (rule === "bool") (out as Record<string, unknown>)[k] = Boolean(v);
    else if (rule === "days") (out as Record<string, unknown>)[k] = v == null || v === "" ? null : clamp(Math.round(Number(v)), 1, 365, k);
    else (out as Record<string, unknown>)[k] = clamp(Number(v), rule[0], rule[1], k);
  }
  return out;
}

function pickPlanner(p: unknown): Partial<PlannerDefaults> {
  if (!p || typeof p !== "object") return {};
  return Object.fromEntries(Object.entries(p).filter(([k]) => k in LIMITS)) as Partial<PlannerDefaults>;
}

function clamp(n: number, lo: number, hi: number, what: string) {
  if (!Number.isFinite(n)) throw new HttpError(400, `${what} must be a number`);
  return Math.min(hi, Math.max(lo, n));
}

export function cleanSellerRules(v: unknown, strict = true): SellerRule[] {
  if (!Array.isArray(v)) {
    if (strict) throw new HttpError(400, "sellerRules must be a list");
    return [];
  }
  const out: SellerRule[] = [];
  for (const r of v.slice(0, 100)) {
    const seller = r && typeof r.seller === "string" ? r.seller.trim().slice(0, 80) : "";
    const mode = r?.mode === "block" || r?.mode === "warn" ? r.mode : null;
    if (!seller || !mode) {
      if (strict) throw new HttpError(400, "each seller rule needs a seller name and mode block or warn");
      continue;
    }
    out.push({ seller, mode, ...(typeof r.note === "string" && r.note ? { note: r.note.slice(0, 200) } : {}) });
  }
  return out;
}

export function cleanOrigins(v: unknown): string[] {
  if (!Array.isArray(v)) throw new HttpError(400, "defaultOrigins must be a list of airport codes");
  const out = [...new Set(v.map((c) => String(c).trim().toUpperCase()).filter(Boolean))];
  if (out.length > 12 || out.some((c) => !/^[A-Z]{3,4}$/.test(c))) throw new HttpError(400, "defaultOrigins must be up to 12 airport or area codes");
  return out;
}

export function cleanCurrency(v: unknown): string {
  if (typeof v !== "string" || !(CURRENCIES as readonly string[]).includes(v)) throw new HttpError(400, "unsupported currency");
  return v;
}
