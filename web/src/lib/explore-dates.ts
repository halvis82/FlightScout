import { addDays, dayDiff } from "./format";
import type { Destination } from "./types";

export function matchesExploreDates(
  offer: Pick<Destination, "departure" | "return_date">,
  depart: string,
  ret: string,
  flex: number,
  retFlex: number,
  roundTrip: boolean,
): boolean {
  return !!offer.departure && offer.departure >= addDays(depart, -flex) && offer.departure <= addDays(depart, flex) &&
    (!roundTrip || (!!offer.return_date && offer.return_date >= addDays(ret, -retFlex) && offer.return_date <= addDays(ret, retFlex)));
}

// "Any dates" still means the trip length asked for: a weekend search must not
// list the week long trips the tracker saved. One way offers always fit.
export function fitsTripLength(
  offer: Pick<Destination, "departure" | "return_date">,
  nightsMin: number | null,
  nightsMax: number | null,
): boolean {
  if (nightsMin == null || nightsMax == null) return true;
  if (!offer.departure || !offer.return_date) return false;
  const n = dayDiff(offer.departure, offer.return_date);
  return n >= nightsMin && n <= nightsMax;
}
