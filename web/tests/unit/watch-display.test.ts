import { describe, expect, it, vi } from "vitest";

const CITIES: Record<string, string> = { OSL: "Oslo", TRF: "Oslo", CDG: "Paris", ORY: "Paris", LAX: "Los Angeles", SAN: "San Diego", CUN: "Cancún", MLM: "Morelia", TIJ: "Tijuana" };
vi.mock("@/lib/airports-client", () => ({ cityOf: (c: string) => CITIES[c] }));
import { airportsLine, alertRule, readable, tripLine, watchTitle } from "@/lib/watch-display";

const base = { origins: ["OSL", "TRF"], destinations: ["CDG", "ORY"], tripType: "oneway" as const, departStart: "2026-12-26", departEnd: "2026-12-26", nightsMin: null, nightsMax: null, cabin: "economy", adults: 1 };

describe("watches in words", () => {
  it("titles generated names by city and keeps names people typed", () => {
    expect(watchTitle({ ...base, name: "OSL/TRF to CDG/ORY" })).toBe("Oslo to Paris");
    expect(watchTitle({ ...base, name: "Christmas in Paris" })).toBe("Christmas in Paris");
    expect(watchTitle({ ...base, name: "LAX/SAN to CDG", origins: ["LAX", "SAN"], destinations: ["CDG"] })).toBe("Los Angeles or San Diego to Paris");
    const legs = [{ origins: ["CUN"], destinations: ["MLM"] }, { origins: ["MLM"], destinations: ["TIJ"] }];
    expect(watchTitle({ ...base, name: "CUN → MLM → TIJ", tripType: "multicity", legs })).toBe("Cancún → Morelia → Tijuana");
  });

  it("keeps the airports, describes the trip and the alert", () => {
    expect(airportsLine({ ...base, name: "x" })).toBe("OSL, TRF → CDG, ORY");
    expect(tripLine({ ...base, name: "x" })).toBe("One way · leaving Sat, Dec 26");
    expect(tripLine({ ...base, name: "x", tripType: "roundtrip", departEnd: "2027-01-02", nightsMin: 5, nightsMax: 7, adults: 2, cabin: "premium" })).toBe(
      "Round trip · leaving Dec 26 to Jan 2 · 5 to 7 nights · 2 travelers · Premium economy",
    );
    const money = (v: number) => `$${v}`;
    expect(alertRule({ alertBelow: 179, alertDropPct: 10, currency: "USD" }, money)).toBe("under $179 or 10% cheaper");
    expect(alertRule({ alertBelow: null, alertDropPct: null, currency: "USD" }, money)).toBeNull();
  });

  it("rewrites codes in alert messages only when every airport is known", () => {
    expect(readable("OSL/TRF to CDG dropped 18% from $122 to $100")).toBe("Oslo to Paris dropped 18% from $122 to $100");
    expect(readable("XYZ to CDG")).toBe("XYZ to Paris");
  });
});
