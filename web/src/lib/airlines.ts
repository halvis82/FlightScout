"use client";
// Airline directory (public/airlines.json, compiled from engine data) and
// deep link building: open an airline's own search pre-filled with a route.

import { useEffect, useState } from "react";

export type Airline = {
  iata: string;
  icao?: string;
  name: string;
  country: string;
  regions: string[];
  category: "full_service" | "low_cost" | "ultra_low_cost" | "hybrid" | "regional" | "premium_leisure";
  tags: string[];
  alliance: "star" | "oneworld" | "skyteam" | null;
  hubs: string[];
  website: string;
  search_url: string;
  deeplink: string | null;
  date_format?: string;
  oneway_deeplink?: string;
  deeplink_verified?: boolean;
  logo: string;
  notes?: string;
};

export const REGIONS: { id: string; label: string }[] = [
  { id: "global", label: "Global networks" },
  { id: "nordics", label: "Nordics" },
  { id: "europe", label: "Europe" },
  { id: "us_domestic", label: "US domestic" },
  { id: "north_america", label: "Canada" },
  { id: "mexico", label: "Mexico" },
  { id: "central_america_caribbean", label: "Central America and Caribbean" },
  { id: "south_america", label: "South America" },
  { id: "middle_east", label: "Middle East" },
  { id: "africa", label: "Africa" },
  { id: "asia", label: "Asia" },
  { id: "oceania", label: "Oceania" },
];

export const CATEGORY_LABEL: Record<Airline["category"], string> = {
  full_service: "Full service",
  low_cost: "Low cost",
  ultra_low_cost: "Ultra low cost",
  hybrid: "Hybrid",
  regional: "Regional",
  premium_leisure: "Premium leisure",
};

let cache: Airline[] | null = null;
let pending: Promise<Airline[]> | null = null;

export function loadAirlines(): Promise<Airline[]> {
  if (cache) return Promise.resolve(cache);
  pending ??= fetch("/airlines.json")
    .then((r) => r.json())
    .then((d: { airlines: Airline[] }) => (cache = d.airlines));
  return pending;
}

export function useAirlines() {
  const [list, setList] = useState<Airline[] | null>(cache);
  useEffect(() => {
    if (!cache) loadAirlines().then(setList).catch(() => setList([]));
  }, []);
  return list;
}

export function airlineByCode(list: Airline[] | null, code: string) {
  return list?.find((a) => a.iata === code) ?? null;
}

const MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
const MON_SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function fmt(iso: string, f = "YYYY-MM-DD") {
  const [y, m, d] = iso.slice(0, 10).split("-");
  switch (f) {
    case "YYYYMMDD":
      return `${y}${m}${d}`;
    case "MM/DD/YYYY":
      return `${m}/${d}/${y}`;
    case "DD/MM/YYYY":
      return `${d}/${m}/${y}`;
    case "DD.MM.YYYY":
      return `${d}.${m}.${y}`;
    case "MMM DD, YYYY":
      return encodeURIComponent(`${MON_SHORT[Number(m) - 1]} ${d}, ${y}`);
    default:
      return `${y}-${m}-${d}`;
  }
}

export type RouteQuery = { origin: string; destination: string; depart: string; ret?: string | null; adults?: number };

// The airline's own search, pre-filled when we know its link format, else its
// plain search page. Returns [url, prefilled].
export function airlineLink(a: Airline, q?: RouteQuery | null): [string, boolean] {
  if (!q || !a.deeplink) return [a.search_url || a.website, false];
  const tpl = !q.ret && a.oneway_deeplink ? a.oneway_deeplink : a.deeplink;
  const f = a.date_format;
  const vals: Record<string, string> = {
    origin: q.origin,
    destination: q.destination,
    adults: String(q.adults ?? 1),
    depart: fmt(q.depart, f),
    return: q.ret ? fmt(q.ret, f) : "",
    depart_mon: MON[Number(q.depart.slice(5, 7)) - 1],
    depart_day: q.depart.slice(8, 10),
    return_mon: q.ret ? MON[Number(q.ret.slice(5, 7)) - 1] : "",
    return_day: q.ret ? q.ret.slice(8, 10) : "",
  };
  return [tpl.replace(/\{(\w+)\}/g, (_, k: string) => vals[k] ?? ""), true];
}
