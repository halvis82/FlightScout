import { route } from "@/lib/api";
import { proxyEngine } from "@/lib/engine-proxy";

export const maxDuration = 120;

// Google Flights parsed from pages the visitor's browser fetched (extension).
export const POST = route((req) => proxyEngine(req, "browser"));
