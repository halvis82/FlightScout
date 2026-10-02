import { describe, expect, it } from "vitest";
import { matchesExploreDates } from "@/lib/explore-dates";

describe("explore date flexibility", () => {
  const matches = (departure: string | null, return_date: string | null, flex = 0, retFlex = 0, roundTrip = true) =>
    matchesExploreDates({ departure, return_date }, "2027-01-02", "2027-01-09", flex, retFlex, roundTrip);
  it("honors exact dates on both ends", () => {
    expect(matches("2027-01-02", "2027-01-09")).toBe(true);
    expect(matches("2027-01-01", "2027-01-09")).toBe(false);
    expect(matches("2027-01-02", "2027-01-08")).toBe(false);
  });
  it("uses independent inclusive windows across year boundaries", () => {
    expect(matches("2026-12-31", "2027-01-10", 2, 1)).toBe(true);
    expect(matches("2027-01-04", "2027-01-08", 2, 1)).toBe(true);
    expect(matches("2026-12-30", "2027-01-09", 2, 1)).toBe(false);
    expect(matches("2027-01-02", "2027-01-11", 2, 1)).toBe(false);
  });
  it("requires known dates and ignores return dates for one-way trips", () => {
    expect(matches(null, null)).toBe(false);
    expect(matches("2027-01-02", null)).toBe(false);
    expect(matches("2027-01-02", null, 0, 0, false)).toBe(true);
  });
});
