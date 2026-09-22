import "server-only";
import { HttpError } from "./api";

// Server side client for the stateless Python engine (engine/src/flightscout/api.py).
export async function engine<T>(path: string, payload?: unknown, timeoutMs = 280_000): Promise<T> {
  const base = process.env.ENGINE_URL;
  if (!base) throw new HttpError(503, "ENGINE_URL is not configured");
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(base.replace(/\/$/, "") + path, {
      method: payload === undefined ? "GET" : "POST",
      headers: {
        "content-type": "application/json",
        "x-engine-key": process.env.ENGINE_KEY ?? "",
      },
      body: payload === undefined ? undefined : JSON.stringify(payload),
      signal: ctrl.signal,
      cache: "no-store",
    });
    const text = await res.text();
    if (!res.ok) {
      let msg = text;
      try {
        const j = JSON.parse(text);
        msg = j.detail ?? j.error ?? text;
      } catch {}
      throw new HttpError(res.status >= 500 ? 502 : res.status, `engine: ${typeof msg === "string" ? msg : JSON.stringify(msg)}`.slice(0, 500));
    }
    return JSON.parse(text) as T;
  } catch (e) {
    if (e instanceof HttpError) throw e;
    if ((e as Error).name === "AbortError") throw new HttpError(504, "engine timed out");
    throw new HttpError(502, `engine unreachable: ${(e as Error).message}`);
  } finally {
    clearTimeout(timer);
  }
}
