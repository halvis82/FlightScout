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
