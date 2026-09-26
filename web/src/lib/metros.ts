// Area codes (a city's airports together), the same groups as the engine
// (engine/src/flightscout/airports.py). Plain data: usable on the server and in the browser.
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


export function expandCodes(codes: string[]) {
  return [...new Set(codes.flatMap((c) => METROS[c]?.codes ?? [c]))];
}
