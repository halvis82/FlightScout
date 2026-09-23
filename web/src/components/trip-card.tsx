"use client";
import { useState } from "react";
import { ArrowRight, ChevronDown, ExternalLink, Eye, Moon, TriangleAlert } from "lucide-react";
import { Badge, Button } from "./ui";
import { Code } from "./place";
import { airport } from "@/lib/airports-client";
import { airlineByCode, airlineLink, useAirlines, type Airline } from "@/lib/airlines";
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
  alts = [],
  onWatch,
  highlight,
  onHover,
}: {
  trip: Trip;
  alts?: Trip[];
  onWatch?: (t: Trip) => void;
  highlight?: boolean;
  onHover?: (t: Trip | null) => void;
}) {
  const { money, settings } = useApp();
  const [open, setOpen] = useState(false);
  const rules = settings?.sellerRules ?? [];
  const slices = trip.tickets.flatMap((t) => t.slices).sort((a, b) => a.departure.localeCompare(b.departure));
  const badges = [...tripBadges(trip), ...trip.tickets.flatMap((t) => itineraryBadges(t, rules))].filter(
    (b, i, arr) => arr.findIndex((x) => x.label === b.label) === i,
  );
  const single = trip.tickets.length === 1 ? trip.tickets[0] : null;

  const rows: Slice[] = single ? single.slices : slices;
  const warnCount = badges.filter((b) => b.tone === "danger" || b.tone === "warn").length;

  return (
    <div
      onMouseEnter={() => onHover?.(trip)}
      onMouseLeave={() => onHover?.(null)}
      className={cn(
        "rounded-2xl border bg-surface transition-colors",
        highlight ? "border-accent" : "border-border hover:border-border-strong",
      )}
    >
      <div className="flex flex-col gap-3 p-3 sm:flex-row sm:items-center sm:p-4">
        <div className="min-w-0 flex-1 space-y-2.5">
          {rows.map((sl, i) => (
            <SliceRow key={i} sl={sl} />
          ))}
          {(trip.kind !== "single" || trip.stopovers.length > 0 || badges.length > 0) && (
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 pl-11 text-xs text-muted">
              {trip.kind !== "single" && (
                <span className="font-medium text-info">
                  {KIND_LABEL[trip.kind]} · {trip.tickets.length} tickets
                </span>
              )}
              {trip.stopovers.map((s) => (
                <span key={s.airport + s.hours}>
                  {s.hours >= 20 ? `${Math.max(1, Math.round(s.hours / 24))} day${Math.round(s.hours / 24) > 1 ? "s" : ""}` : `${Math.round(s.hours)} h`} in <Code code={s.airport} compact />
                </span>
              ))}
              {badges.length > 0 && (
                <button
                  type="button"
                  onClick={() => setOpen(true)}
                  title={badges.map((b) => b.label + (b.title ? `: ${b.title}` : "")).join("\n")}
                  className={cn("inline-flex items-center gap-1 hover:text-fg", warnCount ? "text-warn" : "text-muted")}
                >
                  <TriangleAlert className="size-3.5" />
                  {badges.map((b) => b.label).slice(0, 2).join(", ")}
                  {badges.length > 2 && ` +${badges.length - 2}`}
                </button>
              )}
            </div>
          )}
        </div>
        <div className="flex items-center justify-between gap-3 border-t border-border pt-3 sm:w-48 sm:flex-col sm:items-end sm:justify-center sm:border-0 sm:pt-0">
          <div className="text-right">
            <div className="text-xl font-semibold tabular-nums" title={`${trip.total_price} ${trip.currency}`}>
              {money(trip.total_price, trip.currency)}
            </div>
            <div className="text-[11px] text-muted">{single ? (single.slices.length > 1 ? "round trip" : "one way") : `${trip.tickets.length} tickets total`}</div>
            {alts.length > 0 && (
              <button type="button" onClick={() => setOpen(true)} className="text-[11px] text-accent hover:underline">
                +{alts.length} return option{alts.length > 1 ? "s" : ""}
              </button>
            )}
            {trip.savings_vs_direct != null && trip.savings_vs_direct > 0 && (
              <div className="text-xs font-medium text-good">saves {money(trip.savings_vs_direct, trip.currency)}</div>
            )}
          </div>
          <div className="flex items-center gap-1">
            {single ? (
              <a
                href={single.booking_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex h-9 items-center gap-1.5 rounded-full border border-border-strong px-3.5 text-sm font-medium hover:bg-surface-2"
              >
                {sellerName(single)} <ExternalLink className="size-3.5 text-muted" />
              </a>
            ) : (
              <button
                type="button"
                onClick={() => setOpen(true)}
                className="inline-flex h-9 items-center rounded-full border border-border-strong px-3.5 text-sm font-medium hover:bg-surface-2"
              >
                Book {trip.tickets.length} tickets
              </button>
            )}
            <button
              type="button"
              className="grid size-9 place-items-center rounded-full text-muted hover:bg-surface-2 hover:text-fg"
              onClick={() => setOpen((o) => !o)}
              aria-label="Details"
            >
              <ChevronDown className={cn("size-4 transition-transform", open && "rotate-180")} />
            </button>
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
          {alts.length > 0 && <OtherReturns trip={trip} alts={alts} />}
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

// Same outbound, different return flights (collapsed from the list).
function OtherReturns({ trip, alts }: { trip: Trip; alts: Trip[] }) {
  const { money } = useApp();
  const rows = [trip, ...alts].slice(0, 12);
  return (
    <div className="mb-3 rounded-lg border border-border">
      <div className="border-b border-border bg-surface-2 px-3 py-1.5 text-xs font-medium">Return options with this outbound</div>
      <div className="divide-y divide-border">
        {rows.map((t) => {
          const r = t.tickets[0].slices[1];
          return (
            <a
              key={t.id}
              href={t.tickets[0].booking_url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-3 px-3 py-2 text-sm hover:bg-surface-2"
            >
              <span className="w-28 tabular-nums">
                {formatTime(r.departure)} – {formatTime(r.arrival)}
              </span>
              <span className="w-24 text-muted">{formatDate(r.departure)}</span>
              <span className="w-20 text-muted">{formatDuration(r.duration_min)}</span>
              <span className="flex-1 truncate text-muted">
                {r.stops === 0 ? "Nonstop" : `${r.stops} stop${r.stops > 1 ? "s" : ""}`} · {[...new Set(r.segments.map((x) => x.carrier_name ?? x.carrier))].join(", ")}
              </span>
              <span className="font-semibold tabular-nums">{money(t.total_price, t.currency)}</span>
              <ExternalLink className="size-3.5 text-muted" />
            </a>
          );
        })}
      </div>
    </div>
  );
}

// "Check on <airline>" links: each airline in the ticket, opened on its own
// site with this ticket's route and dates pre-filled when the airline supports it.
function AirlineLinks({ it }: { it: Itinerary }) {
  const list = useAirlines();
  if (!list) return null;
  const out = it.slices[0];
  const back = it.trip_type === "roundtrip" ? it.slices[1] : null;
  const codes = [...new Set(it.slices.flatMap((s) => s.segments.map((x) => x.carrier)))];
  const links = codes
    .map((c) => airlineByCode(list, c))
    .filter((a): a is Airline => Boolean(a))
    .map((a) => {
      // if the airline only flies part of the trip, prefill its own legs
      const segs = it.slices.flatMap((s) => s.segments).filter((x) => x.carrier === a.iata);
      const whole = segs.length === it.slices.reduce((n, s) => n + s.segments.length, 0);
      const q = whole
        ? { origin: out.origin, destination: out.destination, depart: out.departure, ret: back?.departure ?? null }
        : { origin: segs[0].origin, destination: segs[0].destination, depart: segs[0].departure, ret: null };
      const [url] = airlineLink(a, q);
      return { a, url };
    });
  if (!links.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5 border-t border-border px-3 py-2 text-xs">
      <span className="text-muted">Check on the airline:</span>
      {links.map(({ a, url }) => (
        <a
          key={a.iata}
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 rounded-full border border-border px-2 py-0.5 hover:bg-surface-2"
        >
          <AirlineLogo code={a.iata} name={a.name} className="size-4 rounded" />
          {a.name}
          <ExternalLink className="size-3 text-muted" />
        </a>
      ))}
    </div>
  );
}

export function AirlineLogo({ code, name, className }: { code: string; name?: string | null; className?: string }) {
  // Kiwi's CDN first, then avs.io, then the code as a badge.
  const [attempt, setAttempt] = useState(0);
  const srcs = [`https://images.kiwi.com/airlines/64/${code}.png`, `https://pics.avs.io/64/64/${code}.png`];
  if (attempt >= srcs.length)
    return (
      <span className={cn("grid size-8 place-items-center rounded-lg bg-surface-2 text-[10px] font-semibold text-muted", className)} title={name ?? code}>
        {code}
      </span>
    );
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={srcs[attempt]}
      alt={name ?? code}
      title={name ?? code}
      onError={() => setAttempt((n) => n + 1)}
      className={cn("size-8 rounded-lg bg-white object-contain p-0.5", className)}
      loading="lazy"
    />
  );
}

function SliceRow({ sl }: { sl: Slice }) {
  const carriers = [...new Map(sl.segments.map((x) => [x.carrier, x.carrier_name ?? x.carrier])).entries()];
  const plus = dayDiff(sl.departure, sl.arrival);
  const layovers = sl.segments.slice(1).map((s, i) => ({ at: s.origin, min: minutesBetween(sl.segments[i].arrival, s.departure) }));
  return (
    <div className="grid grid-cols-[32px_minmax(0,1fr)] items-center gap-3 sm:grid-cols-[32px_minmax(0,1.3fr)_minmax(0,1fr)_minmax(0,1fr)]">
      <div className="relative size-8">
        <AirlineLogo code={carriers[0][0]} name={carriers[0][1]} />
        {carriers.length > 1 && (
          <span className="absolute -bottom-1 -right-1 rounded-full bg-surface px-1 text-[9px] font-semibold text-muted ring-1 ring-border">
            +{carriers.length - 1}
          </span>
        )}
      </div>
      <div className="min-w-0">
        <div className="text-[15px] font-semibold tabular-nums">
          {formatTime(sl.departure)} – {formatTime(sl.arrival)}
          {plus > 0 && <sup className="ml-0.5 text-[10px] font-medium text-warn">+{plus}</sup>}
        </div>
        <div className="truncate text-xs text-muted">
          {formatDate(sl.departure)} · {carriers.map((c) => c[1]).join(", ")}
        </div>
      </div>
      <div className="hidden min-w-0 sm:block">
        <div className="text-sm">{formatDuration(sl.duration_min)}</div>
        <div className="truncate text-xs text-muted">
          <span title={`${sl.origin} to ${sl.destination}`}>
            {airport(sl.origin)?.city ?? sl.origin} – {airport(sl.destination)?.city ?? sl.destination}
          </span>
        </div>
      </div>
      <div className="col-start-2 min-w-0 sm:col-start-auto">
        <div className="text-sm">
          {sl.stops === 0 ? <span className="text-good">Nonstop</span> : `${sl.stops} stop${sl.stops > 1 ? "s" : ""}`}
          <span className="text-muted sm:hidden"> · {formatDuration(sl.duration_min)}</span>
        </div>
        {layovers.length > 0 && (
          <div className="truncate text-xs text-muted">
            {layovers.map((l, i) => (
              <span key={i}>
                {i > 0 && ", "}
                {formatDuration(l.min)} {l.at}
              </span>
            ))}
          </div>
        )}
      </div>
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
      <AirlineLinks it={it} />
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
