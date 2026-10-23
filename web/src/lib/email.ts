import "server-only";
import { createHmac, timingSafeEqual } from "node:crypto";
import { METROS } from "./metros";
import { formatPrice } from "./format";

// The emails FlightScout sends: one branded layout, with a plain text twin of
// every message and a working unsubscribe link on every alert.

export const siteUrl = (path = "") => `${process.env.BETTER_AUTH_URL ?? "https://flightscout-app.vercel.app"}${path}`;

export type Email = { subject: string; html: string; text: string; unsubscribe?: string };

const esc = (s: string) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);

// ---- unsubscribe links: signed, so they work without signing in ----------
const sign = (userId: string) =>
  createHmac("sha256", process.env.BETTER_AUTH_SECRET ?? "flightscout").update(`unsubscribe:${userId}`).digest("base64url").slice(0, 32);

export function unsubscribeQuery(userId: string) {
  return `u=${encodeURIComponent(userId)}&s=${sign(userId)}`;
}

export function checkUnsubscribe(userId: string | null | undefined, s: string | null | undefined) {
  if (!userId || !s) return false;
  const a = Buffer.from(sign(userId));
  const b = Buffer.from(s);
  return a.length === b.length && timingSafeEqual(a, b);
}

// ---- layout ---------------------------------------------------------------
const C = { accent: "#1d5fd6", text: "#1a1f2b", muted: "#5b6475", faint: "#8a92a3", bg: "#f3f5f9", card: "#ffffff", line: "#e4e8ef" };
const FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif";

type Layout = {
  preheader: string; // the preview line in the inbox
  greeting?: string;
  title: string;
  hero?: { price: string; was?: string }; // big price under the title
  paragraphs: string[]; // plain text, escaped here
  details?: string; // small gray line, e.g. the trip's dates
  button?: { label: string; url: string };
  link?: { label: string; url: string }; // secondary link under the button
  why: string; // why you got this email
  unsubscribeUrl?: string;
};

function layout(l: Layout): { html: string; text: string } {
  const p = (s: string, style = "") => `<p style="margin:0 0 14px;font-size:15px;line-height:22px;color:${C.text};${style}">${s}</p>`;
  const footerLinks = [
    l.unsubscribeUrl && `<a href="${esc(l.unsubscribeUrl)}" style="color:${C.muted};text-decoration:underline">Unsubscribe</a>`,
    `<a href="${esc(siteUrl("/settings"))}" style="color:${C.muted};text-decoration:underline">Email settings</a>`,
    `<a href="${esc(siteUrl("/login"))}" style="color:${C.muted};text-decoration:underline">Sign in to FlightScout</a>`,
  ].filter(Boolean).join(" &nbsp;·&nbsp; ");

  const html = `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light"><title>${esc(l.title)}</title></head>
<body style="margin:0;padding:0;background:${C.bg};-webkit-text-size-adjust:100%">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent">${esc(l.preheader)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:${C.bg};font-family:${FONT}">
<tr><td align="center" style="padding:28px 16px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:520px">
<tr><td style="padding:0 4px 18px">
<a href="${esc(siteUrl("/"))}" style="text-decoration:none;color:${C.text}">
<img src="${esc(siteUrl("/email-logo.png"))}" width="32" height="32" alt="" style="vertical-align:middle;border:0;border-radius:8px">
<span style="vertical-align:middle;margin-left:8px;font-size:18px;font-weight:700;color:${C.text}">FlightScout</span>
</a></td></tr>
<tr><td style="background:${C.card};border:1px solid ${C.line};border-radius:14px;padding:28px 26px">
${l.greeting ? p(esc(l.greeting)) : ""}
<h1 style="margin:0 0 ${l.hero ? 6 : 14}px;font-size:21px;line-height:28px;font-weight:700;color:${C.text}">${esc(l.title)}</h1>
${l.hero ? `<p style="margin:0 0 16px;font-size:34px;line-height:42px;font-weight:800;color:${C.accent}">${esc(l.hero.price)}${l.hero.was ? ` <span style="font-size:16px;font-weight:500;color:${C.faint};text-decoration:line-through">${esc(l.hero.was)}</span>` : ""}</p>` : ""}
${l.paragraphs.map((s) => p(esc(s))).join("\n")}
${l.details ? p(esc(l.details), `font-size:13px;line-height:19px;color:${C.muted}`) : ""}
${l.button ? `<table role="presentation" cellpadding="0" cellspacing="0" style="margin:8px 0 ${l.link ? 12 : 4}px"><tr><td style="background:${C.accent};border-radius:10px"><a href="${esc(l.button.url)}" style="display:inline-block;padding:12px 22px;font-size:15px;font-weight:700;color:#ffffff;text-decoration:none">${esc(l.button.label)}</a></td></tr></table>` : ""}
${l.link ? `<p style="margin:0;font-size:14px"><a href="${esc(l.link.url)}" style="color:${C.accent};text-decoration:none;font-weight:600">${esc(l.link.label)} &rarr;</a></p>` : ""}
</td></tr>
<tr><td style="padding:18px 6px 0;font-size:12px;line-height:18px;color:${C.faint}">
${esc(l.why)}<br>${footerLinks}
</td></tr>
</table></td></tr></table>
</body></html>`;

  const text = [
    l.greeting,
    l.title + (l.hero ? `\n${l.hero.price}${l.hero.was ? ` (was ${l.hero.was})` : ""}` : ""),
    ...l.paragraphs,
    l.details,
    l.button && `${l.button.label}: ${l.button.url}`,
    l.link && `${l.link.label}: ${l.link.url}`,
    "--",
    l.why,
    l.unsubscribeUrl && `Unsubscribe: ${l.unsubscribeUrl}`,
    `Email settings: ${siteUrl("/settings")}`,
  ].filter(Boolean).join("\n\n");
  return { html, text };
}

const hi = (name?: string | null) => {
  const first = name?.trim().split(/\s+/)[0];
  return first ? `Hi ${first},` : "Hi,";
};

// ---- place names: "OSL/TRF to CDG/ORY/BVA" reads "Oslo to Paris" ---------
let cities: Promise<Map<string, string>> | null = null;
function cityMap() {
  cities ??= fetch(siteUrl("/airports.json"), { signal: AbortSignal.timeout(5000) })
    .then((r) => (r.ok ? r.json() : []))
    .then((rows: { iata: string; city?: string }[]) => new Map(rows.filter((r) => r.city).map((r) => [r.iata, r.city!.replace(/\s*\(.*\)\s*$/, "").trim()])))
    .catch(() => {
      cities = null; // try again next time
      return new Map<string, string>();
    });
  return cities;
}

export async function readableRoute(name: string) {
  const map = await cityMap();
  const city = (code: string) => (METROS[code] ? METROS[code].label.replace(/\s*\(.*\)$/, "").replace(/ area$/, "") : map.get(code));
  return name.replace(/\b[A-Z]{3,4}(?:\/[A-Z]{3,4})*\b/g, (group) => {
    const names = group.split("/").map((c) => city(c) ?? c);
    return [...new Set(names)].join("/");
  });
}

// ---- the emails -------------------------------------------------------------
const day = (d: string, year = true) =>
  new Date(`${d}T12:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", ...(year && { year: "numeric" }), timeZone: "UTC" });
// "Dec 26, 2026" or "Dec 26 to Dec 30, 2026"
const dateRange = (a: string, b: string) =>
  a === b ? day(a) : `${day(a, a.slice(0, 4) !== b.slice(0, 4))} to ${day(b)}`;

export type AlertWatch = {
  id: number;
  name: string;
  tripType: string;
  departStart: string;
  departEnd: string;
  nightsMin: number | null;
  nightsMax: number | null;
  adults: number;
  currency: string;
};

export async function priceAlertEmail(o: {
  user: { id: string; name?: string | null; email: string };
  watch: AlertWatch;
  price: number;
  prev: number | null;
  reasons: string[];
  bookingUrl: string | null;
}): Promise<Email> {
  const { watch } = o;
  const route = await readableRoute(watch.name);
  const price = formatPrice(o.price, watch.currency);
  const dates = `leaving ${dateRange(watch.departStart, watch.departEnd)}`;
  const nights =
    watch.tripType === "roundtrip" && watch.nightsMin != null
      ? watch.nightsMax != null && watch.nightsMax !== watch.nightsMin ? ` · ${watch.nightsMin} to ${watch.nightsMax} nights` : ` · ${watch.nightsMin} nights`
      : "";
  const kind = { roundtrip: "Round trip", oneway: "One way", multicity: "Multi city" }[watch.tripType] ?? "Trip";
  const people = `${watch.adults} ${watch.adults === 1 ? "traveler" : "travelers"}`;
  const history = siteUrl(`/watches/${watch.id}`);
  const fare = o.bookingUrl && /^https?:\/\//.test(o.bookingUrl) ? o.bookingUrl : null;
  const reason = o.reasons.join(" and ");
  const unsubscribe = siteUrl(`/unsubscribe?${unsubscribeQuery(o.user.id)}`);
  return {
    subject: `${route} is now ${price}`,
    unsubscribe: siteUrl(`/api/v1/unsubscribe?${unsubscribeQuery(o.user.id)}`),
    ...layout({
      preheader: `The price ${reason}.`,
      greeting: hi(o.user.name),
      title: o.reasons.some((r) => r.startsWith("dropped")) ? `Price drop: ${route}` : `${route} reached your price`,
      hero: { price, was: o.prev != null && o.prev > o.price ? formatPrice(o.prev, watch.currency) : undefined },
      paragraphs: [`The best price on your watch ${reason}. Prices change often, so it may not last.`],
      details: `${kind} · ${dates}${nights} · ${people}`,
      button: fare ? { label: "See this fare", url: fare } : { label: "See price history", url: history },
      link: fare ? { label: "See price history", url: history } : undefined,
      why: `You're getting this because price alerts are on for ${o.user.email}.`,
      unsubscribeUrl: unsubscribe,
    }),
  };
}

export function testEmail(user: { id: string; name?: string | null; email: string }): Email {
  return {
    subject: "Your FlightScout email alerts are working",
    unsubscribe: siteUrl(`/api/v1/unsubscribe?${unsubscribeQuery(user.id)}`),
    ...layout({
      preheader: "This is the test email you asked for.",
      greeting: hi(user.name),
      title: "Email alerts are working",
      paragraphs: [
        "This is the test email you asked for in FlightScout settings.",
        "When a flight on your watchlist drops in price or reaches the price you want, we'll email you here. We check prices twice a day and never email about the same flight more than once every 12 hours.",
      ],
      button: { label: "Open my watchlist", url: siteUrl("/watches") },
      why: `You're getting this because price alerts are on for ${user.email}.`,
      unsubscribeUrl: siteUrl(`/unsubscribe?${unsubscribeQuery(user.id)}`),
    }),
  };
}

export function confirmEmail(user: { name?: string | null; email: string }, url: string): Email {
  return {
    subject: "Confirm your email for FlightScout",
    ...layout({
      preheader: "One click to finish setting up your account.",
      greeting: hi(user.name),
      title: "Confirm your email",
      paragraphs: [`Click the button to confirm ${user.email} and finish signing in to FlightScout.`],
      button: { label: "Confirm my email", url },
      why: "You're getting this because someone signed up for FlightScout with this address. If it wasn't you, ignore this email and nothing will happen.",
    }),
  };
}
