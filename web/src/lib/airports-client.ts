"use client";
import { useEffect, useState } from "react";

export type AirportRow = { iata: string; name: string; city: string; country: string; lat: number; lon: number; size: "L" | "M" };

// Same metro groups as the engine (engine/src/flightscout/airports.py).
export const METROS: Record<string, { label: string; codes: string[] }> = {
  NYC: { label: "New York (all airports)", codes: ["JFK", "EWR", "LGA"] },
  LON: { label: "London (all airports)", codes: ["LHR", "LGW", "STN", "LTN", "LCY", "SEN"] },
  PAR: { label: "Paris (all airports)", codes: ["CDG", "ORY", "BVA"] },
  TYO: { label: "Tokyo (all airports)", codes: ["HND", "NRT"] },
  CHI: { label: "Chicago (all airports)", codes: ["ORD", "MDW"] },
  WAS: { label: "Washington (all airports)", codes: ["IAD", "DCA", "BWI"] },
  MIL: { label: "Milan (all airports)", codes: ["MXP", "LIN", "BGY"] },
  ROM: { label: "Rome (all airports)", codes: ["FCO", "CIA"] },
  STO: { label: "Stockholm (all airports)", codes: ["ARN", "BMA", "NYO"] },
  OSLX: { label: "Oslo area (OSL, TRF, RYG)", codes: ["OSL", "TRF", "RYG"] },
  BAY: { label: "San Francisco Bay Area", codes: ["SFO", "OAK", "SJC"] },
  LAXX: { label: "Los Angeles area", codes: ["LAX", "BUR", "LGB", "SNA", "ONT"] },
  SEL: { label: "Seoul (all airports)", codes: ["ICN", "GMP"] },
  SAO: { label: "Sao Paulo (all airports)", codes: ["GRU", "CGH", "VCP"] },
  BUE: { label: "Buenos Aires (all airports)", codes: ["EZE", "AEP"] },
  MIA: { label: "Miami area", codes: ["MIA", "FLL"] },
  HOU: { label: "Houston (all airports)", codes: ["IAH", "HOU"] },
  BKK: { label: "Bangkok (all airports)", codes: ["BKK", "DMK"] },
  IST: { label: "Istanbul (all airports)", codes: ["IST", "SAW"] },
};

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

export function searchAirports(rows: AirportRow[], q: string, limit = 8) {
  const s = q.trim().toLowerCase();
  if (!s) return [];
  const scored: [number, AirportRow][] = [];
  for (const r of rows) {
    let score = -1;
    const code = r.iata.toLowerCase();
    if (code === s) score = 100;
    else if (code.startsWith(s)) score = 60;
    else if (r.city.toLowerCase().startsWith(s)) score = 50;
    else if (r.city.toLowerCase().includes(s)) score = 30;
    else if (r.name.toLowerCase().includes(s)) score = 20;
    if (score >= 0) scored.push([score + (r.size === "L" ? 5 : 0), r]);
  }
  scored.sort((a, b) => b[0] - a[0]);
  return scored.slice(0, limit).map((x) => x[1]);
}

export function expandCodes(codes: string[]) {
  return [...new Set(codes.flatMap((c) => METROS[c]?.codes ?? [c]))];
}
