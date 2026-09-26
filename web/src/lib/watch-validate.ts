import { HttpError } from "./http-error";
import { CURRENCIES } from "./types";

// Shared by the API routes and the guest router (browser), so guests get the
// same checks as accounts.

export type WatchIn = Partial<{
  name: string;
  origins: string[] | string;
  destinations: string[] | string;
  trip_type: "oneway" | "roundtrip" | "multicity";
  legs?: { origins: string[]; destinations: string[]; date: string; before?: number; after?: number; arrive_by?: string | null }[] | null;
  depart_start: string;
  depart_end: string;
  nights_min: number | null;
  nights_max: number | null;
  cabin: string;
  adults: number;
  max_stops: number | null;
  currency: string;
  include_split: boolean;
  alert_below: number | null;
  alert_drop_pct: number | null;
  active: boolean;
  notes: string | null;
}>;

const CABINS = ["economy", "premium", "business", "first"];

function codes(v: unknown, what: string) {
  const raw = Array.isArray(v) ? v : typeof v === "string" ? v.split(",") : null;
  if (!raw) throw new HttpError(400, `${what} must be a list of airport codes`);
  const out = [...new Set(raw.map((c) => String(c).trim().toUpperCase()).filter(Boolean))];
  if (!out.length || out.length > 12 || out.some((c) => !/^[A-Z]{3,4}$/.test(c)))
    throw new HttpError(400, `${what} must be 1 to 12 airport or area codes like OSL or NYC`);
  return out;
}

// A real calendar date: 2027-02-30 is not one.
export function isDate(s: unknown): s is string {
  if (typeof s !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(s)) return false;
  const d = new Date(s + "T00:00:00Z");
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === s;
}

function int(v: unknown, what: string, min: number, max: number, nullable = true): number | null {
  if (v === null && nullable) return null;
  const n = typeof v === "number" ? v : typeof v === "string" && v.trim() !== "" ? Number(v) : NaN;
  if (!Number.isInteger(n) || n < min || n > max) throw new HttpError(400, `${what} must be a whole number from ${min} to ${max}`);
  return n;
}

function num(v: unknown, what: string, min: number, max: number): number | null {
  if (v === null) return null;
  const n = typeof v === "number" ? v : typeof v === "string" && v.trim() !== "" ? Number(v) : NaN;
  if (!Number.isFinite(n) || n < min || n > max) throw new HttpError(400, `${what} must be a number from ${min} to ${max}`);
  return n;
}

// Map snake_case API input to drizzle columns, validating as we go.
export function toColumns(p: WatchIn, partial: boolean) {
  if (!p || typeof p !== "object") throw new HttpError(400, "expected a JSON object");
  const out: Record<string, unknown> = {};
  if (p.name !== undefined) out.name = String(p.name).trim().slice(0, 120);
  if (p.origins !== undefined) out.origins = codes(p.origins, "origins");
  if (p.destinations !== undefined) out.destinations = codes(p.destinations, "destinations");
  if (p.trip_type !== undefined) {
    if (!["oneway", "roundtrip", "multicity"].includes(p.trip_type)) throw new HttpError(400, "trip_type must be oneway, roundtrip or multicity");
    out.tripType = p.trip_type;
  }
  if (p.legs !== undefined) {
    if (p.legs && (!Array.isArray(p.legs) || !p.legs.length || p.legs.length > 8)) throw new HttpError(400, "legs must be a list of 1 to 8 flights");
    out.legs = p.legs
      ? p.legs.map((l, i) => {
          if (!l || !isDate(l.date)) throw new HttpError(400, `flight ${i + 1} needs a date YYYY-MM-DD`);
          if (l.arrive_by != null && !isDate(l.arrive_by)) throw new HttpError(400, `flight ${i + 1}: arrive_by must be YYYY-MM-DD`);
          return {
            origins: codes(l.origins, `flight ${i + 1} origins`),
            destinations: codes(l.destinations, `flight ${i + 1} destinations`),
            date: l.date,
            before: int(l.before ?? 0, "before", 0, 60, false),
            after: int(l.after ?? 0, "after", 0, 60, false),
            arrive_by: l.arrive_by ?? null,
          };
        })
      : null;
  }
  if (p.depart_start !== undefined) {
    if (!isDate(p.depart_start)) throw new HttpError(400, "depart_start must be a real date YYYY-MM-DD");
    out.departStart = p.depart_start;
  }
  if (p.depart_end !== undefined) {
    if (!isDate(p.depart_end)) throw new HttpError(400, "depart_end must be a real date YYYY-MM-DD");
    out.departEnd = p.depart_end;
  }
  if (p.nights_min !== undefined) out.nightsMin = int(p.nights_min, "nights_min", 0, 365);
  if (p.nights_max !== undefined) out.nightsMax = int(p.nights_max, "nights_max", 0, 365);
  if (p.cabin !== undefined) {
    if (!CABINS.includes(p.cabin)) throw new HttpError(400, `cabin must be one of ${CABINS.join(", ")}`);
    out.cabin = p.cabin;
  }
  if (p.adults !== undefined) out.adults = int(p.adults, "adults", 1, 9, false);
  if (p.max_stops !== undefined) out.maxStops = int(p.max_stops, "max_stops", 0, 3);
  if (p.currency !== undefined) {
    if (!(CURRENCIES as readonly string[]).includes(p.currency)) throw new HttpError(400, "unsupported currency");
    out.currency = p.currency;
  }
  if (p.include_split !== undefined) out.includeSplit = Boolean(p.include_split);
  if (p.alert_below !== undefined) out.alertBelow = num(p.alert_below, "alert_below", 0.01, 10_000_000);
  if (p.alert_drop_pct !== undefined) out.alertDropPct = num(p.alert_drop_pct, "alert_drop_pct", 1, 99);
  if (p.active !== undefined) out.active = Boolean(p.active);
  if (p.notes !== undefined) {
    if (p.notes !== null && (typeof p.notes !== "string" || p.notes.length > 1000)) throw new HttpError(400, "notes must be text up to 1000 characters");
    out.notes = p.notes;
  }

  if (!partial) {
    for (const k of ["origins", "destinations", "departStart"]) {
      if (!out[k] || (Array.isArray(out[k]) && !(out[k] as unknown[]).length)) throw new HttpError(400, `${k} is required`);
    }
    out.departEnd ??= out.departStart;
    out.name ||= `${(out.origins as string[]).join("/")} to ${(out.destinations as string[]).join("/")}`;
  }
  return out;
}

// Checks that need the whole watch (after merging an edit into the stored one).
export function checkWatch(w: { departStart: string; departEnd: string; nightsMin?: number | null; nightsMax?: number | null; tripType?: string }) {
  if (w.departEnd < w.departStart) throw new HttpError(400, "the last departure date is before the first");
  if (w.nightsMin != null && w.nightsMax != null && w.nightsMax < w.nightsMin) throw new HttpError(400, "the longest stay is shorter than the shortest");
}
