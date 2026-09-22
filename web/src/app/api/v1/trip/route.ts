import { route } from "@/lib/api";
import { proxyEngine } from "@/lib/engine-proxy";

export const maxDuration = 300;

export const POST = route((req) => proxyEngine(req, "trip"));
