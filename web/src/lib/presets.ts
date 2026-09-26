import { addDays } from "./format";

type Dates = { tripType: "roundtrip" | "oneway" | "multicity"; depart: string; ret: string; flex: number; retFlex: number };

// Quick trip lengths. Weekend moves departure to the next Friday (from the
// currently chosen date) and returns Sunday, with a day of flexibility. The
// week lengths are exact (dropping the weekend's flexibility).
export function preset(key: string, f: Dates): Partial<Dates> {
  if (key === "oneway") return { tripType: "oneway" };
  if (key === "weekend") {
    const d = new Date(f.depart + "T12:00");
    const toFri = (5 - d.getDay() + 7) % 7;
    const fri = addDays(f.depart, toFri);
    return { tripType: "roundtrip", depart: fri, ret: addDays(fri, 2), flex: 1, retFlex: 1 };
  }
  const n = key === "week" ? 7 : 14;
  return { tripType: "roundtrip", ret: addDays(f.depart, n), flex: 0, retFlex: 0 };
}
