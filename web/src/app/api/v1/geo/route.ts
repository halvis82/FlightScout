import { json, route } from "@/lib/api";

// Roughly where the visitor is (city level), to start their first search from
// the nearest airport. On Vercel this comes free with the request headers; a
// local copy has none, so it asks a free IP lookup for this computer's own
// public address. Nothing is stored on the server.
export const GET = route(async (req) => {
  const h = req.headers;
  const lat = Number(h.get("x-vercel-ip-latitude"));
  const lon = Number(h.get("x-vercel-ip-longitude"));
  if (lat || lon) return json({ lat, lon, city: decodeURIComponent(h.get("x-vercel-ip-city") ?? "") }, { headers: { "Cache-Control": "private, no-store" } });
  if (process.env.FLIGHTSCOUT_NO_RATE_LIMIT === "1") {
    try {
      const r = await fetch("https://ipwho.is/?fields=latitude,longitude,city", { signal: AbortSignal.timeout(3000) });
      const d = (await r.json()) as { latitude?: number; longitude?: number; city?: string };
      if (d.latitude != null) return json({ lat: d.latitude, lon: d.longitude, city: d.city ?? "" });
    } catch {
      /* offline: no suggestion */
    }
  }
  return json({});
});
