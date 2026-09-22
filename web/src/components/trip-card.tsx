"use client";
import { useState } from "react";
import { ArrowRight, ChevronDown, ExternalLink, Eye, Moon, TriangleAlert } from "lucide-react";
import { Badge, Button } from "./ui";
import { useApp } from "./app-context";
import { cn } from "@/lib/utils";
import { dayDiff, formatDate, formatDuration, formatTime, parseLocal } from "@/lib/format";
import { itineraryBadges, ruleFor, tripBadges } from "@/lib/sellers";
import type { Itinerary, Segment, Slice, Trip } from "@/lib/types";

const SOURCE_LABEL: Record<string, string> = { google: "Google Flights", kiwi: "Kiwi.com", ryanair: "Ryanair", serpapi: "Google (SerpApi)" };
const KIND_LABEL: Record<string, string> = {
  single: "One ticket",
  split: "Split ticket",
  stopover: "Stopover",
  nested: "Nested round trips",
  multicity: "Multi city",
};

function minutesBetween(a: string, b: string) {
  const pa = parseLocal(a);
  const pb = parseLocal(b);
  return (Date.UTC(pb.y, pb.mo - 1, pb.da, pb.h, pb.mi) - Date.UTC(pa.y, pa.mo - 1, pa.da, pa.h, pa.mi)) / 60000;
}

export function sellerName(it: Itinerary) {
  return it.seller ?? SOURCE_LABEL[it.source] ?? it.source;
}

export function TripCard({
  trip,
  onWatch,
  highlight,
  onHover,
}: {
  trip: Trip;
  onWatch?: (t: Trip) => void;
  highlight?: boolean;
  onHover?: (t: Trip | null) => void;
}) {
  const { money, settings } = useApp();
  const [open, setOpen] = useState(false);
  const rules = settings?.sellerRules ?? [];
  const slices = trip.tickets.flatMap((t) => t.slices).sort((a, b) => a.departure.localeCompare(b.departure));
  const outbound = trip.tickets.length === 1 ? [trip.tickets[0].slices[0]] : slices;
  const first = slices[0];
  const carriers = [...new Set(slices.flatMap((s) => s.segments.map((x) => x.carrier_name ?? x.carrier)))];
  const badges = [...tripBadges(trip), ...trip.tickets.flatMap((t) => itineraryBadges(t, rules))].filter(
    (b, i, arr) => arr.findIndex((x) => x.label === b.label) === i,
  );
  const outStops = trip.tickets.length === 1 ? trip.tickets[0].slices[0].stops : slices.length - 1;
  const outArrival = trip.tickets.length === 1 ? trip.tickets[0].slices[0].arrival : null;
  const plusDays = outArrival ? dayDiff(first.departure, outArrival) : 0;
  const single = trip.tickets.length === 1 ? trip.tickets[0] : null;
  const routeCodes = single
    ? [single.slices[0].origin, ...single.slices[0].segments.map((s) => s.destination)]
    : trip.route;
  const roundTrip = single ? single.slices.length === 2 && single.slices[1].destination === single.slices[0].origin : false;

  return (
    <div
      onMouseEnter={() => onHover?.(trip)}
      onMouseLeave={() => onHover?.(null)}
      className={cn(
        "rounded-lg border bg-surface transition-colors",
        highlight ? "border-accent" : "border-border hover:border-border-strong",
      )}
    >
      <div className="flex flex-col gap-3 p-3 sm:flex-row sm:items-center">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <div className="flex items-baseline gap-1.5 font-mono text-[15px] font-semibold">
              {routeCodes.map((c, i) => (
                <span key={i} className="flex items-baseline gap-1.5">
                  {i > 0 && <ArrowRight className="size-3 self-center text-faint" />}
                  <span className={cn(i === 0 || i === routeCodes.length - 1 ? "text-fg" : "text-muted")}>{c}</span>
                </span>
              ))}
              {roundTrip && <span className="font-sans text-xs font-normal text-muted">and back</span>}
            </div>
            <Badge tone={trip.kind === "single" ? "neutral" : "info"}>{KIND_LABEL[trip.kind] ?? trip.kind}</Badge>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-sm text-muted">
            <span className="text-fg">
              {formatDate(first.departure)} · {formatTime(first.departure)}
              {outArrival && (
                <>
                  {" "}to {formatTime(outArrival)}
                  {plusDays > 0 && <sup className="ml-0.5 text-[10px] text-warn">+{plusDays}</sup>}
                </>
              )}
            </span>
            <span>{formatDuration(outbound.reduce((s, x) => s + x.duration_min, 0))}</span>
            <span>{outStops === 0 ? "Nonstop" : `${outStops} stop${outStops > 1 ? "s" : ""}`}</span>
            <span className="truncate">{carriers.slice(0, 3).join(", ")}{carriers.length > 3 ? ` +${carriers.length - 3}` : ""}</span>
          </div>
          {trip.tickets.length === 1 && trip.tickets[0].slices[1] && (
            <div className="mt-0.5 text-sm text-muted">
              Return {formatDate(trip.tickets[0].slices[1].departure)} · {formatTime(trip.tickets[0].slices[1].departure)} ·{" "}
              {formatDuration(trip.tickets[0].slices[1].duration_min)} ·{" "}
              {trip.tickets[0].slices[1].stops === 0 ? "Nonstop" : `${trip.tickets[0].slices[1].stops} stops`}
            </div>
          )}
          {(badges.length > 0 || trip.stopovers.length > 0) && (
            <div className="mt-2 flex flex-wrap gap-1">
              {trip.stopovers.map((s) => (
                <Badge key={s.airport + s.hours} tone="info" title="Time on the ground between tickets">
                  {s.hours >= 20 ? `${Math.round(s.hours / 24)}d` : `${Math.round(s.hours)}h`} in {s.airport}
                </Badge>
              ))}
              {badges.map((b) => (
                <Badge key={b.label} tone={b.tone} title={b.title}>
                  {b.label}
                </Badge>
              ))}
            </div>
          )}
        </div>
        <div className="flex items-center justify-between gap-3 sm:flex-col sm:items-end sm:justify-center">
          <div className="text-right">
            <div className="text-lg font-semibold tabular-nums" title={`${trip.total_price} ${trip.currency}`}>
              {money(trip.total_price, trip.currency)}
            </div>
            {single?.price_insight && <div className="max-w-56 text-[11px] leading-tight text-muted">{single.price_insight}</div>}
            {trip.savings_vs_direct != null && trip.savings_vs_direct > 0 && (
              <div className="text-xs font-medium text-good">saves {money(trip.savings_vs_direct, trip.currency)}</div>
            )}
          </div>
          <div className="flex items-center gap-1.5">
            {trip.tickets.length === 1 ? (
              <a
                href={trip.tickets[0].booking_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex h-8 items-center gap-1 rounded-md bg-accent px-3 text-sm font-medium text-accent-fg hover:brightness-110"
              >
                {sellerName(trip.tickets[0])} <ExternalLink className="size-3.5" />
              </a>
            ) : (
              <Button size="sm" variant="primary" onClick={() => setOpen(true)} className="h-8">
                {trip.tickets.length} booking links
              </Button>
            )}
            <Button size="sm" variant="ghost" className="h-8" onClick={() => setOpen((o) => !o)} aria-label="Details">
              <ChevronDown className={cn("size-4 transition-transform", open && "rotate-180")} />
            </Button>
          </div>
        </div>
      </div>
      {open && (
        <div className="border-t border-border px-3 py-3">
          {trip.risks.length > 0 && (
            <ul className="mb-3 space-y-1 rounded-md bg-warn-soft px-3 py-2 text-sm text-warn">
              {trip.risks.map((r) => (
                <li key={r} className="flex gap-2">
                  <TriangleAlert className="mt-0.5 size-3.5 shrink-0" />
                  {r}
                </li>
              ))}
            </ul>
          )}
          <div className="space-y-3">
            {trip.tickets.map((t, i) => (
              <TicketBlock key={t.id + i} it={t} index={trip.tickets.length > 1 ? i + 1 : undefined} />
            ))}
          </div>
          {onWatch && (
            <div className="mt-3 flex justify-end">
              <Button size="sm" onClick={() => onWatch(trip)}>
                <Eye className="size-3.5" /> Watch this route
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function TicketBlock({ it, index }: { it: Itinerary; index?: number }) {
  const { money, settings } = useApp();
  const badges = itineraryBadges(it, settings?.sellerRules ?? []);
  return (
    <div className="rounded-md border border-border">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-surface-2 px-3 py-2">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          {index && <span className="font-semibold">Ticket {index}</span>}
          <span className="text-muted">sold via</span>
          <span className="font-medium">{sellerName(it)}</span>
          <Badge>{SOURCE_LABEL[it.source] ?? it.source}</Badge>
          {badges.map((b) => (
            <Badge key={b.label} tone={b.tone} title={b.title}>
              {b.label}
            </Badge>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <span className="font-semibold tabular-nums">{money(it.price, it.currency)}</span>
          <a
            href={it.booking_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex h-7 items-center gap-1 rounded-md bg-accent px-2.5 text-xs font-medium text-accent-fg hover:brightness-110"
          >
            Open on {sellerName(it)} <ExternalLink className="size-3" />
          </a>
        </div>
      </div>
      {it.price_insight && <div className="border-b border-border px-3 py-1.5 text-xs text-muted">{it.price_insight}</div>}
      <div className="divide-y divide-border">
        {it.slices.map((s, i) => (
          <SliceTimeline key={i} slice={s} label={it.slices.length > 1 ? (i === 0 ? "Outbound" : i === 1 && it.trip_type === "roundtrip" ? "Return" : `Leg ${i + 1}`) : undefined} />
        ))}
      </div>
      <OffersPanel it={it} />
      {it.warnings.length > 0 && (
        <ul className="space-y-0.5 border-t border-border px-3 py-2 text-xs text-muted">
          {it.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
      {it.baggage && (
        <div className="border-t border-border px-3 py-1.5 text-xs text-muted">
          Included bags: {Object.entries(it.baggage).map(([k, v]) => `${v} ${k.replace(/([A-Z])/g, " $1").toLowerCase()}`).join(", ")}
        </div>
      )}
    </div>
  );
}

function SliceTimeline({ slice, label }: { slice: Slice; label?: string }) {
  return (
    <div className="px-3 py-2">
      {label && (
        <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-faint">
          {label} · {formatDate(slice.departure)} · {formatDuration(slice.duration_min)}
        </div>
      )}
      <ol className="space-y-1.5">
        {slice.segments.map((seg, i) => (
          <li key={i}>
            {i > 0 && <Layover prev={slice.segments[i - 1]} next={seg} />}
            <SegmentRow seg={seg} />
          </li>
        ))}
      </ol>
    </div>
  );
}

function SegmentRow({ seg }: { seg: Segment }) {
  const plus = dayDiff(seg.departure, seg.arrival);
  return (
    <div className="grid grid-cols-[auto_1fr_auto] items-center gap-3 text-sm">
      <div className="w-24 font-mono tabular-nums">
        {formatTime(seg.departure)}–{formatTime(seg.arrival)}
        {plus > 0 && <sup className="text-[10px] text-warn">+{plus}</sup>}
      </div>
      <div className="min-w-0">
        <span className="font-mono font-semibold">{seg.origin}</span>
        <ArrowRight className="mx-1 inline size-3 text-faint" />
        <span className="font-mono font-semibold">{seg.destination}</span>
        <span className="ml-2 text-muted">
          {seg.carrier_name ?? seg.carrier} {seg.carrier}
          {seg.flight_number}
        </span>
        {seg.aircraft && <span className="ml-2 hidden text-faint md:inline">{seg.aircraft}</span>}
      </div>
      <div className="text-xs text-muted">{formatDuration(seg.duration_min ?? minutesBetween(seg.departure, seg.arrival))}</div>
    </div>
  );
}

function Layover({ prev, next }: { prev: Segment; next: Segment }) {
  const min = minutesBetween(prev.arrival, next.departure);
  const change = prev.destination !== next.origin;
  const overnight = parseLocal(prev.arrival).da !== parseLocal(next.departure).da;
  return (
    <div
      className={cn(
        "my-1 ml-24 flex items-center gap-2 border-l-2 border-dashed pl-3 text-xs",
        change || min < 60 ? "border-bad text-bad" : min > 8 * 60 ? "border-warn text-warn" : "border-border text-muted",
      )}
    >
      {formatDuration(min)} layover in {prev.destination}
      {change && <span className="font-medium">· change to {next.origin}</span>}
      {overnight && (
        <span className="inline-flex items-center gap-0.5">
          · <Moon className="size-3" /> overnight
        </span>
      )}
    </div>
  );
}

function OffersPanel({ it }: { it: Itinerary }) {
  const { money, settings } = useApp();
  const [open, setOpen] = useState(false);
  const rules = settings?.sellerRules ?? [];
  if (!it.offers?.length) {
    if (it.source !== "google") return null;
    return (
      <div className="border-t border-border px-3 py-1.5 text-xs text-faint">
        Seller breakdown available from the CLI (<code>flightscout search ... --sellers 5</code>) and in tracked watches.
      </div>
    );
  }
  const visible = it.offers
    .filter((o) => ruleFor(rules, o.seller)?.mode !== "block")
    .sort((a, b) => Number(b.is_airline) - Number(a.is_airline) || Math.min(...a.fares.map((f) => f.price)) - Math.min(...b.fares.map((f) => f.price)));
  const hidden = it.offers.length - visible.length;
  return (
    <div className="border-t border-border">
      <button onClick={() => setOpen((o) => !o)} className="flex w-full items-center gap-1 px-3 py-1.5 text-left text-xs font-medium text-accent hover:bg-surface-2">
        <ChevronDown className={cn("size-3.5 transition-transform", open && "rotate-180")} />
        Sellers and fares ({visible.length}){hidden > 0 && <span className="font-normal text-muted"> · {hidden} hidden by your rules</span>}
      </button>
      {open && (
        <div className="space-y-2 px-3 pb-3">
          {visible.map((o) => {
            const rule = ruleFor(rules, o.seller);
            return (
              <div key={o.seller} className="rounded-md border border-border">
                <div className="flex items-center gap-2 border-b border-border bg-surface-2 px-2.5 py-1.5 text-sm">
                  <span className="font-medium">{o.seller}</span>
                  <Badge tone={o.is_airline ? "good" : "warn"}>{o.is_airline ? "Airline" : "Agency"}</Badge>
                  {rule?.mode === "warn" && (
                    <Badge tone="warn" title={rule.note}>
                      Flagged
                    </Badge>
                  )}
                </div>
                <ul className="divide-y divide-border">
                  {o.fares.map((f, i) => (
                    <li key={i} className="flex items-start gap-3 px-2.5 py-1.5 text-sm">
                      <div className="min-w-0 flex-1">
                        <div>{f.name ?? "Fare"}</div>
                        {f.features.length > 0 && <div className="text-xs text-muted">{f.features.join(" · ")}</div>}
                      </div>
                      <span className="font-medium tabular-nums">{money(f.price, it.currency)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
