import { json, route } from "@/lib/api";
import { getRates } from "@/lib/fx";

// Same for everyone and updated daily: served from Vercel's edge cache.
export const GET = route(async () =>
  json(
    { base: "EUR", rates: await getRates() },
    { headers: { "Cache-Control": "public, s-maxage=3600, stale-while-revalidate=86400" } },
  ),
);
