import type { SellerRule } from "./db/schema";
import type { Itinerary, Trip } from "./types";

// A seller rule the engine reads as "also show sellers other than airlines and
// major booking sites, flagged" (the Settings checkbox, off by default).
// "*unverified" was an older, narrower switch the engine no longer reads.
export const SHOW_UNRELIABLE = "*unreliable";
const SWITCHES = new Set([SHOW_UNRELIABLE, "*unverified"]);

// Engine calls that return trips, and so take seller rules.
export const SELLER_KINDS = new Set(["search", "plan", "browser", "trip", "multicity"]);

export const showsUnreliable = (rules: SellerRule[]) => rules.some((r) => r.seller === SHOW_UNRELIABLE);
export const isSwitch = (r: SellerRule) => SWITCHES.has(r.seller);

// The rules the engine needs: hidden sellers, plus the checkbox. Warn rules
// are applied here in the browser instead.
export function engineSellerRules(rules: SellerRule[]): Record<string, string> | undefined {
  const sent = rules.filter((r) => (r.mode === "block" && !isSwitch(r)) || r.seller === SHOW_UNRELIABLE);
  return sent.length ? Object.fromEntries(sent.map((r) => [r.seller, r.mode])) : undefined;
}

// Presets users can add with one click. These sellers are hidden unless the
// Settings checkbox includes less reliable booking sites.
export const SELLER_PRESETS: SellerRule[] = [
  { seller: "Kiwi.com", mode: "warn", note: "OTA. Self transfers are covered by the Kiwi Guarantee, not the airlines." },
  { seller: "Gotogate", mode: "warn", note: "OTA with frequent service complaints." },
  { seller: "Mytrip", mode: "warn", note: "OTA (Etraveli group)." },
  { seller: "Trip.com", mode: "warn", note: "OTA." },
  { seller: "eDreams", mode: "warn", note: "OTA with paid Prime pricing shown by default." },
  { seller: "Opodo", mode: "warn", note: "OTA with paid Prime pricing shown by default." },
  { seller: "BudgetAir", mode: "warn", note: "OTA." },
  { seller: "Kiwi.com", mode: "block", note: "Hide every Kiwi.com result." },
];

export function ruleFor(rules: SellerRule[], seller?: string | null) {
  if (!seller) return undefined;
  const s = seller.toLowerCase();
  return rules.find((r) => !isSwitch(r) && s.includes(r.seller.toLowerCase()));
}

export function isBlocked(rules: SellerRule[], it: Itinerary) {
  return ruleFor(rules, it.seller)?.mode === "block";
}

export function tripBlocked(rules: SellerRule[], t: Trip) {
  return t.tickets.some((it) => isBlocked(rules, it));
}

export type Badge = { label: string; tone: "warn" | "danger" | "info"; title?: string };

// Warning badges derived from the itinerary itself, independent of user rules.
export function itineraryBadges(it: Itinerary, rules: SellerRule[] = []): Badge[] {
  const out: Badge[] = [];
  if (it.self_transfer)
    out.push({ label: "Self transfer", tone: "danger", title: "Connections are not protected by the airlines. Collect and recheck bags." });
  if (it.seller_kind === "ota")
    out.push({ label: "Travel agency", tone: "warn", title: `Sold by ${it.seller ?? "an online travel agency"}, not the airline.` });
  for (const sl of it.slices) {
    for (let i = 1; i < sl.segments.length; i++) {
      if (sl.segments[i].origin !== sl.segments[i - 1].destination) {
        out.push({
          label: "Airport change",
          tone: "danger",
          title: `Arrive ${sl.segments[i - 1].destination}, depart ${sl.segments[i].origin}`,
        });
      }
    }
  }
  // engine warnings about fares and sellers become badges too
  for (const w of it.warnings) {
    if (/is basic/i.test(w)) out.push({ label: "Basic fare", tone: "warn", title: w });
    else if (/no free carry-on/i.test(w)) out.push({ label: "No carry-on", tone: "warn", title: w });
    else if (/only sold by travel agencies/i.test(w)) out.push({ label: "Agencies only", tone: "warn", title: w });
    else if (/not the airline or a major booking site/.test(w)) out.push({ label: "Less reliable seller", tone: "danger", title: w });
    else if (/couldn't verify as an established company/.test(w)) out.push({ label: "Unverified agency", tone: "danger", title: w });
    // "Lands at TRF (Sandefjord, Torp), 122 km from OSL" shows as "Lands at TRF"
    else if (/^(Lands at|Leaves from) /.test(w)) out.push({ label: w.split(",")[0].replace(/\s*\(.*$/, "").trim(), tone: "warn", title: w });
  }
  const rule = ruleFor(rules, it.seller);
  if (rule?.mode === "warn") out.push({ label: `Flagged: ${rule.seller}`, tone: "warn", title: rule.note });
  return dedupe(out);
}

export function tripBadges(t: Trip): Badge[] {
  const out: Badge[] = [];
  if (t.tickets.length > 1)
    out.push({
      label: `${t.tickets.length} separate tickets`,
      tone: "danger",
      title: "Each ticket is booked separately. A delay on one does not protect the next.",
    });
  if (t.kind === "stopover" || t.kind === "nested")
    out.push({ label: "Stopover", tone: "info", title: t.stopovers.map((s) => `${s.airport} ${Math.round(s.hours)}h`).join(", ") });
  return out;
}

function dedupe(b: Badge[]) {
  const seen = new Set<string>();
  return b.filter((x) => (seen.has(x.label) ? false : (seen.add(x.label), true)));
}
