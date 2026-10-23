"use client";
import { cityOf } from "./airports-client";
import { formatDate } from "./format";
import type { WatchRow } from "./watch-types";

// Watches in words people read: "Oslo to Paris", not "OSL/TRF to CDG/ORY/BVA".
// Cities come from the airport list, so callers render under useAirports().

type WatchLike = Pick<WatchRow, "name" | "origins" | "destinations" | "tripType" | "departStart" | "departEnd" | "nightsMin" | "nightsMax" | "cabin" | "adults"> & {
  legs?: unknown;
};

// "Oslo", or "Los Angeles or San Diego" for airports in different cities
export function placeNames(codes: string[]) {
  const names = [...new Set(codes.map((c) => cityOf(c) ?? c))];
  return names.length > 2 ? `${names.slice(0, 2).join(", ")} +${names.length - 2}` : names.join(" or ");
}

// Codes in any text become cities: "OSL/TRF to CDG dropped 10%" reads "Oslo to Paris dropped 10%".
export function readable(text: string) {
  return text.replace(/\b[A-Z]{3,4}(?:\/[A-Z]{3,4})*\b/g, (group) => {
    const parts = group.split("/");
    const names = parts.map((c) => cityOf(c));
    if (names.some((n) => !n)) return group; // not all airports (or not loaded yet)
    return [...new Set(names)].join("/");
  });
}

const legsOf = (w: WatchLike) =>
  Array.isArray(w.legs) ? (w.legs as { origins: string[]; destinations: string[] }[]) : [];

// A name made up only of airport codes was generated, not typed by someone.
const generated = (name: string) => /^(?:[A-Z]{3,4}|\/|\s|to|→|⇄|->)+$/.test(name.trim());

// The big title: the name someone gave it, else the cities.
export function watchTitle(w: WatchLike) {
  if (w.name && !generated(w.name)) return w.name;
  const legs = legsOf(w);
  if (w.tripType === "multicity" && legs.length) return [placeNames(legs[0].origins), ...legs.map((l) => placeNames(l.destinations))].join(" → ");
  if (w.tripType === "multicity") return readable(w.name);
  return `${placeNames(w.origins)} to ${placeNames(w.destinations)}`;
}

// The airports themselves, small under the title: "OSL, TRF → CDG, ORY, BVA"
export function airportsLine(w: WatchLike) {
  const legs = legsOf(w);
  if (w.tripType === "multicity" && legs.length) return [legs[0].origins.join(", "), ...legs.map((l) => l.destinations.join(", "))].join(" → ");
  return `${w.origins.join(", ")} ${w.tripType === "roundtrip" ? "⇄" : "→"} ${w.destinations.join(", ")}`;
}

// "One way · Fri, Dec 26" / "Round trip · Mar 18 to Mar 25 · 7 to 10 nights · 2 travelers · Business"
export function tripLine(w: WatchLike) {
  const kind = w.tripType === "roundtrip" ? "Round trip" : w.tripType === "oneway" ? "One way" : "Multi city";
  const when = w.departStart === w.departEnd ? formatDate(w.departStart) : `${formatDate(w.departStart, false)} to ${formatDate(w.departEnd, false)}`;
  const parts = [kind, w.tripType === "multicity" ? when : `leaving ${when}`];
  if (w.tripType === "roundtrip" && w.nightsMin != null)
    parts.push(w.nightsMax != null && w.nightsMax !== w.nightsMin ? `${w.nightsMin} to ${w.nightsMax} nights` : `${w.nightsMin} night${w.nightsMin === 1 ? "" : "s"}`);
  if (w.adults > 1) parts.push(`${w.adults} travelers`);
  if (w.cabin !== "economy") parts.push(w.cabin === "premium" ? "Premium economy" : w.cabin[0].toUpperCase() + w.cabin.slice(1));
  return parts.join(" · ");
}

// When this watch alerts, in a sentence: "under $179 or 10% cheaper"
export function alertRule(w: Pick<WatchRow, "alertBelow" | "alertDropPct" | "currency">, money: (v: number, c: string) => string) {
  const rules = [
    w.alertBelow != null && `under ${money(w.alertBelow, w.currency)}`,
    w.alertDropPct != null && `${w.alertDropPct}% cheaper`,
  ].filter(Boolean);
  return rules.length ? rules.join(" or ") : null;
}
