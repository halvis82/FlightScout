"""Parser for Navitaire dotREZ availability responses (the nsk v4
``availability/search`` shape: ``results[].trips[].journeysAvailableByMarket``
plus a ``faresAvailable`` table). Several low cost carriers put their web
booking engine straight on dotREZ (Akasa, IndiGo, Jazeera, ...); the airline
modules fetch the JSON their own way and share this parser."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def _offset(local: str | None, utc: str | None) -> timezone | None:
    if not local or not utc:
        return None
    try:
        d = datetime.fromisoformat(local) - datetime.fromisoformat(utc.replace("Z", ""))
    except ValueError:
        return None
    return timezone(timedelta(minutes=round(d.total_seconds() / 60)))


def _iso(local: str, tz: timezone | None) -> str:
    dt = datetime.fromisoformat(local)
    return (dt.replace(tzinfo=tz) if tz else dt).isoformat()


def _fares_table(data: dict) -> dict:
    fa = data.get("faresAvailable") or {}
    if isinstance(fa, list):  # [{"key": .., "value": ..}] in newer dotREZ versions
        fa = {x.get("key"): x.get("value") for x in fa}
    return fa


def fare_amount(fare: dict, ptype: str = "ADT") -> float | None:
    """Per passenger price of one faresAvailable entry, incl. taxes and fees
    (dotREZ ``fareAmount`` with taxesAndFees requested), summed over its
    segment fares."""
    tot, found = 0.0, False
    for f in fare.get("fares") or []:
        for pf in f.get("passengerFares") or []:
            if pf.get("passengerType") == ptype and pf.get("fareAmount") is not None:
                tot += pf["fareAmount"]
                found = True
                break
    return tot if found else None


def parse_availability(data: dict, adults: int = 1, skip_fees: tuple[str, ...] = ()) -> list[list[dict]]:
    """dotREZ availability JSON (the ``data`` object) -> one list of journey
    dicts (see _airline.py) per trip, each journey at its cheapest available
    fare for ``adults`` adults. ``skip_fees`` names service charge codes to
    leave out of the price."""
    fares = _fares_table(data)
    out: list[list[dict]] = []
    for res in data.get("results") or []:
        for trip in res.get("trips") or []:
            js = []
            markets = trip.get("journeysAvailableByMarket") or {}
            if isinstance(markets, dict):
                journeys = [j for v in markets.values() for j in v]
            else:
                journeys = [j for m in markets for j in (m.get("value") or [])]
            for j in journeys:
                best = None
                for ref in j.get("fares") or []:
                    f = fares.get(ref.get("fareAvailabilityKey"))
                    if not f:
                        continue
                    seats = min((d.get("availableCount") or 0 for d in ref.get("details") or []), default=None)
                    if seats is not None and seats < adults:
                        continue
                    amt = fare_amount(f)
                    if amt is None:
                        continue
                    if skip_fees:
                        amt -= sum(sc.get("amount") or 0 for x in f.get("fares") or []
                                   for pf in x.get("passengerFares") or [] if pf.get("passengerType") == "ADT"
                                   for sc in pf.get("serviceCharges") or [] if sc.get("code") in skip_fees)
                    pc = next((x.get("productClass") for x in f.get("fares") or []), None)
                    if best is None or amt < best[0]:
                        best = (amt, pc, seats)
                if not best:
                    continue
                segs = []
                for s in j.get("segments") or []:
                    legs = s.get("legs") or []
                    li0 = (legs[0].get("legInfo") or {}) if legs else {}
                    li1 = (legs[-1].get("legInfo") or {}) if legs else {}
                    des, ident = s["designator"], s["identifier"]
                    segs.append({
                        "origin": des["origin"], "destination": des["destination"],
                        "departure": _iso(des["departure"], _offset(li0.get("departureTime"),
                                                                    li0.get("departureTimeUtc"))),
                        "arrival": _iso(des["arrival"], _offset(li1.get("arrivalTime"), li1.get("arrivalTimeUtc"))),
                        "carrier": ident["carrierCode"], "number": ident["identifier"],
                        "aircraft": li0.get("equipmentType"),
                    })
                if segs:
                    js.append({"segments": segs, "total": round(best[0] * adults, 2), "fare": best[1],
                               "seats": best[2]})
            out.append(js)
    return out
