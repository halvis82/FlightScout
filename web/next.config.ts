import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // PGlite (local dev database) loads its wasm/data files from its own
  // package folder, which breaks when bundled.
  serverExternalPackages: ["@electric-sql/pglite"],
};

export default nextConfig;
