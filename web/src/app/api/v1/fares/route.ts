import { json, route, HttpError } from "@/lib/api";
import { knownFares } from "@/lib/fares";

// Fares this site has seen (USD, cheapest per airport) from an origin and to a
// destination: layover hints for smart routes run on the visitor's own
// computer (the website adds them itself for server side plans).
export const GET = route(async (req) => {
  const p = new URL(req.url).searchParams;
  const code = (k: string) => {
    const v = (p.get(k) ?? "").toUpperCase();
    if (!/^[A-Z]{3}$/.test(v)) throw new HttpError(400, `${k} must be an airport code`);
    return v;
  };
  const day = (k: string) => {
    const v = p.get(k) ?? "";
    if (!/^\d{4}-\d{2}-\d{2}$/.test(v)) throw new HttpError(400, `${k} must be a date`);
    return v;
  };
  const lo = day("from");
  const hi = day("to");
  if (hi < lo || Date.parse(hi) - Date.parse(lo) > 40 * 86400_000) throw new HttpError(400, "bad date range");
  return json(await knownFares(code("origin"), code("destination"), lo, hi), {
    headers: { "Cache-Control": "public, s-maxage=600" },
  });
});
