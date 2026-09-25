import type { NextConfig } from "next";

const DAY = "public, max-age=86400, stale-while-revalidate=604800";

const nextConfig: NextConfig = {
  // PGlite (local dev database) loads its wasm/data files from its own
  // package folder, which breaks when bundled.
  serverExternalPackages: ["@electric-sql/pglite"],
  // Static data every visitor loads (airports, airlines, the map worker):
  // cache it in the browser instead of revalidating on every page view.
  async headers() {
    return ["/airports.json", "/airlines.json", "/maplibre/:path*"].map((source) => ({
      source,
      headers: [{ key: "Cache-Control", value: DAY }],
    }));
  },
};

export default nextConfig;
