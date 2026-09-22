import { HttpError } from "@/lib/api";
import { CURRENCIES } from "@/lib/types";

export type WatchIn = Partial<{
  name: string;
  origins: string[] | string;
  destinations: string[] | string;
  trip_type: "oneway" | "roundtrip";
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

const codes = (v: string[] | string) =>
  (Array.isArray(v) ? v : v.split(","))
    .map((c) => c.trim().toUpperCase())
    .filter((c) => /^[A-Z]{3,4}$/.test(c));

const isDate = (s: string) => /^\d{4}-\d{2}-\d{2}$/.test(s);

// Map snake_case API input to drizzle columns, validating as we go.
export function toColumns(p: WatchIn, partial: boolean) {
  const out: Record<string, unknown> = {};
  if (p.name !== undefined) out.name = String(p.name).slice(0, 120);
  if (p.origins !== undefined) out.origins = codes(p.origins);
  if (p.destinations !== undefined) out.destinations = codes(p.destinations);
  if (p.trip_type !== undefined) out.tripType = p.trip_type === "oneway" ? "oneway" : "roundtrip";
  if (p.depart_start !== undefined) {
    if (!isDate(p.depart_start)) throw new HttpError(400, "depart_start must be YYYY-MM-DD");
    out.departStart = p.depart_start;
  }
  if (p.depart_end !== undefined) {
    if (!isDate(p.depart_end)) throw new HttpError(400, "depart_end must be YYYY-MM-DD");
    out.departEnd = p.depart_end;
  }
  if (p.nights_min !== undefined) out.nightsMin = p.nights_min;
  if (p.nights_max !== undefined) out.nightsMax = p.nights_max;
  if (p.cabin !== undefined) out.cabin = p.cabin;
  if (p.adults !== undefined) out.adults = Math.max(1, Math.min(9, Number(p.adults)));
  if (p.max_stops !== undefined) out.maxStops = p.max_stops;
  if (p.currency !== undefined) {
    if (!(CURRENCIES as readonly string[]).includes(p.currency)) throw new HttpError(400, "unsupported currency");
    out.currency = p.currency;
  }
  if (p.include_split !== undefined) out.includeSplit = Boolean(p.include_split);
  if (p.alert_below !== undefined) out.alertBelow = p.alert_below;
  if (p.alert_drop_pct !== undefined) out.alertDropPct = p.alert_drop_pct;
  if (p.active !== undefined) out.active = Boolean(p.active);
  if (p.notes !== undefined) out.notes = p.notes;

  if (!partial) {
    for (const k of ["origins", "destinations", "departStart"]) {
      if (!out[k] || (Array.isArray(out[k]) && !(out[k] as unknown[]).length))
        throw new HttpError(400, `${k} is required`);
    }
    out.departEnd ??= out.departStart;
    out.name ??= `${(out.origins as string[]).join("/")} to ${(out.destinations as string[]).join("/")}`;
  }
  if (out.departStart && out.departEnd && (out.departEnd as string) < (out.departStart as string))
    throw new HttpError(400, "depart_end is before depart_start");
  return out;
}
