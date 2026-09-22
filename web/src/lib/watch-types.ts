// Watch row as returned by GET /watches (server) or the guest router.
export type WatchRow = {
  id: number;
  name: string;
  origins: string[];
  destinations: string[];
  tripType: "oneway" | "roundtrip";
  departStart: string;
  departEnd: string;
  nightsMin: number | null;
  nightsMax: number | null;
  cabin: string;
  adults: number;
  maxStops: number | null;
  currency: string;
  includeSplit: boolean;
  alertBelow: number | null;
  alertDropPct: number | null;
  active: boolean;
  lastCheckedAt: string | null;
  bestPrice: number | null;
  prevPrice: number | null;
  lowestPrice: number | null;
  bestTrip: unknown;
  notes: string | null;
  sparkline?: { day: string; price: number }[];
};
