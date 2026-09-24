// Identity of a watch or place, so the same one can't be saved twice (double
// clicks, retries, CLI and website). Must match the SQL backfill in
// drizzle/0004_watch_signature_legs.sql for existing rows.

const sorted = (xs: string[] | null | undefined) => [...(xs ?? [])].map((x) => x.toUpperCase()).sort().join(",");

export function watchSignature(w: {
  origins: string[];
  destinations: string[];
  tripType?: string | null;
  departStart: string;
  departEnd?: string | null;
  nightsMin?: number | null;
  nightsMax?: number | null;
  cabin?: string | null;
  adults?: number | null;
  legs?: unknown;
}) {
  return [
    sorted(w.origins),
    sorted(w.destinations),
    w.tripType ?? "roundtrip",
    w.departStart,
    w.departEnd ?? w.departStart,
    w.nightsMin ?? "",
    w.nightsMax ?? "",
    w.cabin ?? "economy",
    String(w.adults ?? 1),
    w.legs ? JSON.stringify(w.legs) : "",
  ].join("|");
}

export const placeSignature = (codes: string[]) => sorted(codes);
