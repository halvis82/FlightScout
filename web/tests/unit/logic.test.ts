import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { priceScale } from "@/lib/price-scale";
import { airlineLink, type Airline } from "@/lib/airlines";
import { addDays, dayDiff, formatPrice } from "@/lib/format";
import { preset } from "@/lib/presets";
import { searchAirports, expandCodes, type AirportRow } from "@/lib/airports-client";

const rows = JSON.parse(readFileSync("public/airports.json", "utf8")) as AirportRow[];
const airlines = (JSON.parse(readFileSync("public/airlines.json", "utf8")) as { airlines: Airline[] }).airlines;

describe("prices", () => {
  it("never abbreviates", () => {
    expect(formatPrice(1000, "USD")).toMatch(/1,000/);
    expect(formatPrice(12450, "NOK")).toMatch(/12,450|12 450/);
    expect(formatPrice(1000, "USD")).not.toMatch(/k/i);
  });
  it("colors cheapest green and priciest red, robust to outliers", () => {
    const s = priceScale([100, 110, 120, 130, 5000]);
    expect(s.t(100)).toBe(0);
    expect(s.t(5000)).toBe(1);
    expect(s.t(120)).toBeGreaterThan(0.3); // rank based: the outlier doesn't squash the middle to green
    expect(s.solid(100)).toContain("150"); // green hue
  });
});

describe("dates and presets", () => {
  it("weekend moves to the next Friday and returns Sunday with flex", () => {
    const p = preset("weekend", { tripType: "oneway", depart: "2026-10-06", ret: "2026-10-13", flex: 0, retFlex: 0 }); // a Tuesday
    expect(p.depart).toBe("2026-10-09");
    expect(p.ret).toBe("2026-10-11");
    expect(p.tripType).toBe("roundtrip");
    expect(p.flex).toBe(1);
  });
  it("1 and 2 week trips keep departure", () => {
    const f = { tripType: "roundtrip" as const, depart: "2026-10-06", ret: "2026-10-08", flex: 0, retFlex: 0 };
    expect(preset("week", f).ret).toBe("2026-10-13");
    expect(dayDiff("2026-10-06", preset("twoweeks", f).ret!)).toBe(14);
    expect(addDays("2026-12-31", 1)).toBe("2027-01-01");
  });
});

describe("airports", () => {
  it("finds cities accent insensitively, codes first, local names too", () => {
    expect(searchAirports(rows, "cancun")[0].iata).toBe("CUN");
    expect(searchAirports(rows, "osl")[0].iata).toBe("OSL");
    expect(searchAirports(rows, "san jose del cabo").map((r) => r.iata)).toContain("SJD");
    expect(searchAirports(rows, "milan").map((r) => r.iata)).toContain("MXP");
  });
  it("expands metros", () => {
    expect(expandCodes(["NYC"])).toEqual(["JFK", "EWR", "LGA"]);
  });
});

describe("airline deep links", () => {
  const q = { origin: "OSL", destination: "CPH", depart: "2026-11-20", ret: "2026-11-27", adults: 2 };
  it("fills every placeholder for every airline with a template", () => {
    for (const a of airlines.filter((x) => x.deeplink)) {
      const [url, prefilled] = airlineLink(a, q);
      expect(prefilled).toBe(true);
      expect(url, a.name).not.toMatch(/\{\w+\}/);
      expect(url.startsWith("http")).toBe(true);
    }
  });
  it("uses each airline's date format", () => {
    const sas = airlines.find((a) => a.iata === "SK")!;
    expect(airlineLink(sas, q)[0]).toContain("OSL-CPH-20261120-20261127");
    const volaris = airlines.find((a) => a.iata === "Y4")!;
    expect(airlineLink(volaris, { ...q, origin: "TIJ", destination: "GDL" })[0]).toContain("11/20/2026");
  });
  it("falls back to the search page without a route", () => {
    for (const a of airlines) expect(airlineLink(a, null)[1]).toBe(false);
  });
});
