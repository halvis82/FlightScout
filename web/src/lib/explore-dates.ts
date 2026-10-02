import { addDays } from "./format";
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
