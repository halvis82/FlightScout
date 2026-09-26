"use client";
import { useEffect, useState } from "react";

export type AirportRow = { iata: string; name: string; city: string; country: string; lat: number; lon: number; size: "L" | "M"; alt?: string };

export { METROS, expandCodes } from "./metros";
import { METROS } from "./metros";

let cache: AirportRow[] | null = null;
let byCode: Map<string, AirportRow> | null = null;
let loading: Promise<AirportRow[]> | null = null;

export function loadAirports() {
  if (cache) return Promise.resolve(cache);
  loading ??= fetch("/airports.json")
    .then((r) => r.json())
    .then((rows: AirportRow[]) => {
      cache = rows;
      byCode = new Map(rows.map((r) => [r.iata, r]));
      return rows;
    });
  return loading;
}

export function airport(code: string) {
  return byCode?.get(code.toUpperCase());
}

export function useAirports() {
  const [rows, setRows] = useState<AirportRow[] | null>(cache);
  useEffect(() => {
    if (!rows) loadAirports().then(setRows);
  }, [rows]);
  return { rows, get: (c: string) => (rows ? airport(c) : undefined) };
}

// Accent and case insensitive: "cancun" finds Cancún.
export function fold(s: string) {
  return s.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim();
}

const folded = new WeakMap<AirportRow, { city: string; name: string }>();
function f(r: AirportRow) {
  let v = folded.get(r);
  if (!v) folded.set(r, (v = { city: fold(r.city), name: fold(r.name) }));
  return v;
}

// Exact code first, then city prefix matches, then large airports.
export function searchAirports(rows: AirportRow[], q: string, limit = 8) {
  const s = fold(q);
  if (!s) return [];
  const scored: [number, AirportRow][] = [];
  for (const r of rows) {
    const code = r.iata.toLowerCase();
    const { city, name } = f(r);
    let score = -1;
    if (code === s) score = 1000;
    else if (city === s || city.startsWith(s + " (") || city.startsWith(s + "(")) score = 600;
    else if (city.startsWith(s)) score = 500;
    else if (code.startsWith(s) && s.length >= 2) score = 400;
    else if (city.split(/[\s(/-]+/).some((w) => w.startsWith(s))) score = 300;
    else if (name.includes(s)) score = 200;
    else if (city.includes(s)) score = 150;
    else if (r.alt && fold(r.alt).includes(s)) score = fold(r.alt).startsWith(s) ? 450 : 140; // local name, e.g. San José del Cabo
    if (score >= 0) scored.push([score + (r.size === "L" ? 50 : 0), r]);
  }
  scored.sort((a, b) => b[0] - a[0] || a[1].city.localeCompare(b[1].city));
  return scored.slice(0, limit).map((x) => x[1]);
}


// ---------------------------------------------------------------------------
// display helpers: every code or airport name is shown with its city
// ---------------------------------------------------------------------------

// "Oslo (Gardermoen)" -> "Oslo", "Sandefjord(Torp)" -> "Sandefjord"
function cleanCity(c: string) {
  return c.replace(/\s*\(.*\)\s*$/, "").trim();
}

let regionNames: Intl.DisplayNames | null = null;
export function countryName(cc: string) {
  try {
    regionNames ??= new Intl.DisplayNames(["en"], { type: "region" });
    return regionNames.of(cc) ?? cc;
  } catch {
    return cc;
  }
}

// City for an airport or metro code, or undefined while airports load.
export function cityOf(code: string): string | undefined {
  const m = METROS[code];
  if (m) return m.label.replace(/\s*\(.*\)$/, "").replace(/ area$/, "");
  const a = airport(code);
  return a ? cleanCity(a.city || a.name) : undefined;
}

// "OSL (Oslo)"
export function codeWithCity(code: string) {
  const c = cityOf(code);
  return c ? `${code} (${c})` : code;
}

// "Oslo-Gardermoen" from "Oslo-Gardermoen International Airport"
export function shortAirportName(name: string) {
  return (
    name
      .replace(/\b(International|Intl\.?|Regional|Municipal)\b/g, "")
      .replace(/\bAirport\b/g, "")
      .replace(/\s*,\s*$/, "")
      .replace(/\s{2,}/g, " ")
      .trim() || name
  );
}

// "Oslo-Gardermoen (Oslo)", falls back to the code
export function airportWithCity(code: string) {
  const a = airport(code);
  if (!a) return METROS[code]?.label ?? code;
  const city = cleanCity(a.city || "");
  const short = shortAirportName(a.name);
  return city && short !== city ? `${short} (${city})` : short;
}

// Nearest airport with real service to a point: a large one within 150 km
// (so San Diego gives SAN, not a strip), else the nearest medium one.
export function nearestAirport(rows: AirportRow[], lat: number, lon: number): AirportRow | null {
  const rad = Math.PI / 180;
  const km = (r: AirportRow) => {
    const dLat = (r.lat - lat) * rad;
    const dLon = (r.lon - lon) * rad;
    const a = Math.sin(dLat / 2) ** 2 + Math.cos(lat * rad) * Math.cos(r.lat * rad) * Math.sin(dLon / 2) ** 2;
    return 12742 * Math.asin(Math.sqrt(a));
  };
  let bestL: [number, AirportRow] | null = null;
  let bestAny: [number, AirportRow] | null = null;
  for (const r of rows) {
    const d = km(r);
    if (r.size === "L" && (!bestL || d < bestL[0])) bestL = [d, r];
    if (!bestAny || d < bestAny[0]) bestAny = [d, r];
  }
  if (bestL && bestL[0] <= 150) return bestL[1];
  return bestAny?.[1] ?? null;
}
