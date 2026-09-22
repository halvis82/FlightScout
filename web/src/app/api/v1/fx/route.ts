import { json, route } from "@/lib/api";
import { getRates } from "@/lib/fx";

export const GET = route(async () => json({ base: "EUR", rates: await getRates() }));
