import { describe, expect, it } from "vitest";
import { watchSignature } from "@/lib/signature";

const base = { origins: ["CUN"], destinations: ["TIJ"], tripType: "multicity", departStart: "2026-12-30", departEnd: "2027-01-09" };

describe("watchSignature", () => {
  it("treats the same multi city legs as the same watch however they are serialized", () => {
    const form = [
      { origins: ["CUN"], destinations: ["MLM"], date: "2026-12-30", before: 0, after: 0, arrive_by: null },
      { origins: ["MLM"], destinations: ["TIJ"], date: "2027-01-09", before: 1, after: 1, arrive_by: null },
    ];
    const stored = [
      { date: "2026-12-30", after: "0", before: "0", destinations: ["MLM"], origins: ["cun"] },
      { arrive_by: null, destinations: ["TIJ"], origins: ["MLM"], after: 1, before: 1, date: "2027-01-09" },
    ];
    expect(watchSignature({ ...base, legs: form })).toBe(watchSignature({ ...base, legs: stored }));
  });

  it("different legs are different watches", () => {
    const a = [{ origins: ["CUN"], destinations: ["MLM"], date: "2026-12-30", before: 0, after: 0 }];
    const b = [{ origins: ["CUN"], destinations: ["MLM"], date: "2026-12-30", before: 1, after: 1 }];
    expect(watchSignature({ ...base, legs: a })).not.toBe(watchSignature({ ...base, legs: b }));
  });
});

import { tripsToObservations } from "@/lib/watch-logic";

describe("tripsToObservations", () => {
  it("keeps a round trip 'from' price on its round trip, not as one way", () => {
    const trip = {
      id: "x", kind: "single", total_price: 927, currency: "USD", route: ["LAX", "DPS"], departure: "2027-03-18T22:00:00", travel_min: 2000,
      tickets: [{ source: "google", return_pending: true, pending_return: "2027-03-29", booking_url: "u",
        slices: [{ departure: "2027-03-18T22:00:00", origin: "LAX", destination: "DPS" }] }],
    };
    const [o] = tripsToObservations([trip as never], ["DPS"]);
    expect(o.return_date).toBe("2027-03-29");
  });
});

import { queryMatchesWatch } from "@/lib/watch-logic";

describe("queryMatchesWatch", () => {
  const w = { origins: ["SAN"], destinations: ["OSL"], tripType: "roundtrip" as const, departStart: "2026-11-10", departEnd: "2026-11-14",
    nightsMin: 7, nightsMax: 10, cabin: "economy", adults: 1, maxStops: null, currency: "USD", alertBelow: null, alertDropPct: null };
  const q = { origins: ["SAN"], destinations: ["OSL"], departure: "2026-11-12", return_date: "2026-11-20", cabin: "economy", adults: 1 };
  it("matches the same search", () => expect(queryMatchesWatch(q as never, w as never)).toBe(true));
  it("ignores other party sizes, stops and trip lengths", () => {
    expect(queryMatchesWatch({ ...q, adults: 2 } as never, w as never)).toBe(false);
    expect(queryMatchesWatch({ ...q, max_stops: 0 } as never, w as never)).toBe(false);
    expect(queryMatchesWatch({ ...q, return_date: "2026-11-30" } as never, w as never)).toBe(false);
  });
});

import { safeNext } from "../../src/lib/safe-next";

describe("safeNext", () => {
  it("keeps paths on this site and refuses everything else", () => {
    expect(safeNext("/watches?x=1#a")).toBe("/watches?x=1#a");
    expect(safeNext("javascript:alert(1)")).toBe("/");
    expect(safeNext("https://example.org/x")).toBe("/");
    expect(safeNext("//example.org/x")).toBe("/");
    expect(safeNext("/\\example.org/x")).toBe("/");
    expect(safeNext(null)).toBe("/");
  });
});
