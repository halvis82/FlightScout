import { describe, expect, it } from "vitest";
import { tripsForWatch } from "@/lib/watch-logic";
import { checkWatch, isDate, toColumns } from "@/lib/watch-validate";
import type { Trip } from "@/lib/types";

const slice = (o: string, d: string, dep: string) => ({
  origin: o,
  destination: d,
  departure: `${dep}T10:00:00`,
  arrival: `${dep}T20:00:00`,
  duration_min: 600,
  segments: [],
});
const trip = (route: string[], deps: string[], extra: Partial<Trip["tickets"][0]> = {}): Trip =>
  ({
    id: route.join() + deps.join(),
    tickets: [{ source: "google", price: 500, currency: "USD", slices: deps.map((d, i) => slice(route[i], route[i + 1], d)), ...extra }],
    total_price: 500,
    currency: "USD",
    kind: "single",
    stopovers: [],
    risks: [],
    route,
    departure: `${deps[0]}T10:00:00`,
    arrival: `${deps.at(-1)}T20:00:00`,
    travel_min: 600,
  }) as unknown as Trip;

const watch = {
  origins: ["LAX"],
  destinations: ["DPS"],
  tripType: "roundtrip" as const,
  departStart: "2027-03-15",
  departEnd: "2027-03-20",
  nightsMin: 10,
  nightsMax: 12,
  cabin: "economy",
  adults: 1,
  maxStops: null,
  currency: "USD",
  alertBelow: null,
  alertDropPct: null,
  name: "LAX to DPS",
};

describe("tripsForWatch", () => {
  it("keeps only the watch's route, window and trip length", () => {
    const ok = trip(["LAX", "DPS", "LAX"], ["2027-03-18", "2027-03-29"]);
    const otherPlace = trip(["LAX", "BKK", "LAX"], ["2027-03-18", "2027-03-29"]);
    const tooLate = trip(["LAX", "DPS", "LAX"], ["2027-03-25", "2027-04-05"]);
    const tooShort = trip(["LAX", "DPS", "LAX"], ["2027-03-18", "2027-03-21"]);
    expect(tripsForWatch([ok, otherPlace, tooLate, tooShort], watch)).toEqual([ok]);
  });
  it("counts a round trip priced with the return picked later by the date it was searched for", () => {
    const pending = trip(["LAX", "DPS"], ["2027-03-18"], { return_pending: true, pending_return: "2027-03-29" });
    const pendingShort = trip(["LAX", "DPS"], ["2027-03-18"], { return_pending: true, pending_return: "2027-03-20" });
    expect(tripsForWatch([pending, pendingShort], watch)).toEqual([pending]);
  });
  it("one way watches take one way trips (also split tickets) to a destination", () => {
    const ow = { ...watch, tripType: "oneway" as const, nightsMin: null, nightsMax: null };
    const split = trip(["LAX", "SIN", "DPS"], ["2027-03-18", "2027-03-19"]);
    const rt = trip(["LAX", "DPS", "LAX"], ["2027-03-18", "2027-03-29"]);
    expect(tripsForWatch([split, rt], ow)).toEqual([split]);
  });
  it("area codes cover their airports", () => {
    const nyc = { ...watch, origins: ["NYC"], tripType: "oneway" as const, nightsMin: null, nightsMax: null };
    expect(tripsForWatch([trip(["JFK", "DPS"], ["2027-03-18"])], nyc)).toHaveLength(1);
  });
});

describe("watch validation", () => {
  it("refuses junk and impossible values", () => {
    expect(isDate("2027-02-30")).toBe(false);
    expect(isDate("2027-02-28")).toBe(true);
    const bad = [
      { alert_below: "abc" },
      { adults: "abc" },
      { adults: 12 },
      { depart_start: "2027-02-30" },
      { origins: 123 },
      { origins: ["<script>"] },
      { cabin: "<b>" },
      { max_stops: -3 },
      { alert_drop_pct: -5 },
      { trip_type: "sideways" },
    ];
    for (const b of bad) expect(() => toColumns(b as never, true), JSON.stringify(b)).toThrow();
    expect(() => checkWatch({ departStart: "2027-03-20", departEnd: "2027-03-10" })).toThrow();
    expect(() => checkWatch({ departStart: "2027-03-10", departEnd: "2027-03-20", nightsMin: 9, nightsMax: 3 })).toThrow();
  });
  it("accepts a normal watch", () => {
    const c = toColumns({ origins: "lax", destinations: ["DPS"], depart_start: "2027-03-15", adults: 2, max_stops: 1, alert_below: 450 }, false);
    expect(c).toMatchObject({ origins: ["LAX"], destinations: ["DPS"], departStart: "2027-03-15", departEnd: "2027-03-15", adults: 2, maxStops: 1, alertBelow: 450 });
  });
});
