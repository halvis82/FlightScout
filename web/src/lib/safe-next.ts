// Where to go after signing in: only a path on this same site. Anything else
// (javascript:, another host, //host, /\host) falls back to the home page.
export function safeNext(next: string | null | undefined, origin = "http://localhost"): string {
  if (!next) return "/";
  try {
    const base = new URL(origin);
    const u = new URL(next, base);
    if (u.origin !== base.origin || !["http:", "https:"].includes(u.protocol)) return "/";
    // "/.//evil.com" parses to the path "//evil.com", which a browser reads as another host
    const path = u.pathname.replace(/^[/\\]+/, "/");
    return path + u.search + u.hash || "/";
  } catch {
    return "/";
  }
}
