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
    legsKey(w.legs),
  ].join("|");
}

// Multi city legs in a canonical form: the website's form, the stored row and
// the CLI can serialize the same legs differently (key order, numbers as
// strings, missing nulls), which made a watched search look unwatched.
type LegLike = { origins?: string[]; destinations?: string[]; date?: string; before?: unknown; after?: unknown; arrive_by?: unknown };
export function legsKey(legs: unknown) {
  if (!Array.isArray(legs) || !legs.length) return "";
  return (legs as LegLike[])
    .map((l) => `${sorted(l.origins)}>${sorted(l.destinations)}@${l.date ?? ""}~${Number(l.before ?? 0)}/${Number(l.after ?? 0)}/${l.arrive_by ?? ""}`)
    .join(";");
}

export const placeSignature = (codes: string[]) => sorted(codes);
