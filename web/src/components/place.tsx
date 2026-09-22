"use client";
import { Fragment } from "react";
import { ArrowRight, ArrowLeftRight } from "lucide-react";
import { airportWithCity, cityOf, codeWithCity, useAirports } from "@/lib/airports-client";
import { cn } from "@/lib/utils";

// "OSL (Oslo)", or just the code with the city on hover when compact.
export function Code({ code, compact, className }: { code: string; compact?: boolean; className?: string }) {
  useAirports();
  const city = cityOf(code);
  if (compact || !city)
    return (
      <span className={cn("font-semibold", className)} title={airportWithCity(code)}>
        {code}
      </span>
    );
  return (
    <span className={className} title={airportWithCity(code)}>
      <span className="font-semibold">{code}</span> <span className="text-muted">({city})</span>
    </span>
  );
}

// OSL (Oslo) → LIS (Lisbon) → CUN (Cancún). Compact shows codes, with the
// cities of the first and last stop spelled out.
export function RouteText({ codes, roundTrip, compact, className }: { codes: string[]; roundTrip?: boolean; compact?: boolean; className?: string }) {
  useAirports();
  const Arrow = roundTrip ? ArrowLeftRight : ArrowRight;
  return (
    <span className={cn("inline-flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5", className)}>
      {codes.map((c, i) => {
        const ends = i === 0 || i === codes.length - 1;
        return (
          <Fragment key={i}>
            {i > 0 && <Arrow className="size-3 shrink-0 text-faint" />}
            <Code code={c} compact={compact && !ends} className={!ends ? "text-muted" : undefined} />
          </Fragment>
        );
      })}
    </span>
  );
}

// "OSL, TRF" style lists become "OSL (Oslo), TRF (Sandefjord)"
export function codesWithCities(codes: string[]) {
  return codes.map(codeWithCity).join(", ");
}
