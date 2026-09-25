// Readable watch URLs: /watches/lax-dps-2027-03-18-11n instead of a database
// number. Old /watches/<id> links keep working. When two of your watches
// would share a slug, the id is appended to keep it unique.

type W = { id?: number | string; origins: string[]; destinations: string[]; tripType?: string; departStart: string; nightsMin?: number | null; legs?: unknown };

export function watchSlug(w: W) {
  const legs = Array.isArray(w.legs) ? (w.legs as { destinations?: string[] }[]) : null;
  const stops = w.tripType === "multicity" && legs?.length
    ? [w.origins[0], ...legs.map((l) => l.destinations?.[0] ?? "")]
    : [w.origins[0], w.destinations[0]];
  const parts = [...stops, w.departStart];
  if (w.tripType === "roundtrip" && w.nightsMin != null) parts.push(`${w.nightsMin}n`);
  if (w.tripType === "oneway") parts.push("oneway");
  return parts.filter(Boolean).join("-").toLowerCase();
}

export function watchHref(w: W, all?: W[] | null) {
  const s = watchSlug(w);
  const clash = (all ?? []).some((x) => String(x.id) !== String(w.id) && watchSlug(x) === s);
  return `/watches/${clash ? `${s}-${w.id}` : s}`;
}

// The id a /watches/<param> URL points at, given the user's watches.
export function resolveWatchParam(param: string, all: (W & { id: number | string })[] | undefined): string | null {
  if (/^\d+$/.test(param)) return param;
  if (!all) return null;
  const direct = all.find((w) => watchSlug(w) === param);
  if (direct) return String(direct.id);
  const m = /-(\d+)$/.exec(param);
  const byId = m ? all.find((w) => String(w.id) === m[1]) : undefined;
  return byId ? String(byId.id) : null;
}
