import { HttpError } from "./http-error";
import { placeSignature } from "./signature";

const KINDS = ["home", "frequent", "interested"] as const;
type Kind = (typeof KINDS)[number];
export type PlaceCols = { label?: string; codes?: string[]; kind?: Kind; color?: string | null; notes?: string | null; signature?: string };

// Only these fields can be set, each checked. `partial` for PATCH.
export function placeInput(p: unknown, partial: boolean): PlaceCols {
  if (!p || typeof p !== "object") throw new HttpError(400, "expected a JSON object");
  const b = p as Record<string, unknown>;
  const out: PlaceCols = {};
  if (b.label !== undefined || !partial) {
    const label = typeof b.label === "string" ? b.label.trim() : "";
    if (!label || label.length > 80) throw new HttpError(400, "label is required (up to 80 characters)");
    out.label = label;
  }
  if (b.codes !== undefined || !partial) {
    const raw = Array.isArray(b.codes) ? b.codes : typeof b.codes === "string" ? b.codes.split(",") : null;
    if (!raw) throw new HttpError(400, "codes must be a list of airport codes");
    const codes = [...new Set(raw.map((c) => String(c).trim().toUpperCase()))];
    if (!codes.length || codes.length > 12 || codes.some((c) => !/^[A-Z]{3,4}$/.test(c)))
      throw new HttpError(400, "codes must be 1 to 12 airport or area codes like OSL or NYC");
    out.codes = codes;
    out.signature = placeSignature(codes);
  }
  if (b.kind !== undefined) {
    if (!KINDS.includes(b.kind as Kind)) throw new HttpError(400, `kind must be one of ${KINDS.join(", ")}`);
    out.kind = b.kind as Kind;
  } else if (!partial) out.kind = "frequent";
  for (const k of ["color", "notes"] as const) {
    if (b[k] === undefined) continue;
    if (b[k] !== null && (typeof b[k] !== "string" || (b[k] as string).length > (k === "notes" ? 500 : 32)))
      throw new HttpError(400, `${k} is too long or not text`);
    out[k] = b[k] as string | null;
  }
  return out;
}
