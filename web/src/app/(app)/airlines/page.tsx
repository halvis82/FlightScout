"use client";
import { useMemo, useState } from "react";
import { ExternalLink, Search } from "lucide-react";
import { AirportInput } from "@/components/airport-input";
import { DateRangeField } from "@/components/date-picker";
import { AirlineLogo } from "@/components/trip-card";
import { Segmented, Switch } from "@/components/ui";
import { airport, expandCodes } from "@/lib/airports-client";
import { CATEGORY_LABEL, REGIONS, airlineLink, useAirlines, type Airline } from "@/lib/airlines";
import { addDays, isoDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import directAirlines from "@/lib/direct-airlines.json";

// airline code -> searched directly on every search, or only with a local runner
const DIRECT = directAirlines as Record<string, "everywhere" | "local">;

// Countries to directory regions, so a route can surface the airlines that
// most likely fly it.
const REGION_OF: Record<string, string[]> = {
  NO: ["nordics", "europe"], SE: ["nordics", "europe"], DK: ["nordics", "europe"], FI: ["nordics", "europe"], IS: ["nordics", "europe"],
  US: ["us_domestic", "north_america"], CA: ["north_america"], MX: ["mexico", "central_america_caribbean"],
  BR: ["south_america"], AR: ["south_america"], CL: ["south_america"], CO: ["south_america"], PE: ["south_america"], EC: ["south_america"],
  AE: ["middle_east"], QA: ["middle_east"], SA: ["middle_east"], IL: ["middle_east"], JO: ["middle_east"], OM: ["middle_east"],
  AU: ["oceania"], NZ: ["oceania"], FJ: ["oceania"],
};
const EUROPE = "GB IE FR DE NL BE LU ES PT IT CH AT PL CZ SK HU RO BG GR HR SI RS BA ME AL MK TR CY MT LT LV EE UA MD".split(" ");
const ASIA = "JP KR CN HK TW SG MY TH VN PH ID IN LK NP BD KH LA MM MO".split(" ");
const AFRICA = "ZA KE ET EG MA TN DZ NG GH RW TZ UG SN".split(" ");
const CARIB = "CR PA GT SV HN NI BZ DO PR JM BS CU HT TT BB AW CW".split(" ");

function regionsFor(country?: string) {
  if (!country) return [];
  if (REGION_OF[country]) return REGION_OF[country];
  if (EUROPE.includes(country)) return ["europe"];
  if (ASIA.includes(country)) return ["asia"];
  if (AFRICA.includes(country)) return ["africa"];
  if (CARIB.includes(country)) return ["central_america_caribbean"];
  return [];
}

export default function AirlinesPage() {
  const list = useAirlines();
  const [region, setRegion] = useState<string>("all");
  const [cat, setCat] = useState<string>("all");
  const [q, setQ] = useState("");
  const [onlyDirect, setOnlyDirect] = useState(false);
  const [from, setFrom] = useState<string[]>([]);
  const [to, setTo] = useState<string[]>([]);
  const [depart, setDepart] = useState(() => addDays(isoDate(new Date()), 14));
  const [ret, setRet] = useState(() => addDays(isoDate(new Date()), 21));
  const [oneWay, setOneWay] = useState(false);

  const o = expandCodes(from)[0];
  const d = expandCodes(to)[0];
  const route = o && d ? { origin: o, destination: d, depart, ret: oneWay ? null : ret } : null;
  const routeRegions = useMemo(
    () => new Set([...regionsFor(airport(o ?? "")?.country), ...regionsFor(airport(d ?? "")?.country)]),
    [o, d],
  );

  const shown = useMemo(() => {
    if (!list) return [];
    const needle = q.trim().toLowerCase();
    let r = list.filter(
      (a) =>
        (region === "all" || a.regions.includes(region)) &&
        (cat === "all" || a.category === cat || (cat === "low_cost" && (a.category === "ultra_low_cost" || a.category === "hybrid"))) &&
        (!needle || a.name.toLowerCase().includes(needle) || a.iata.toLowerCase() === needle || a.tags.some((t) => t.includes(needle))) &&
        (!onlyDirect || DIRECT[a.iata] != null),
    );
    if (routeRegions.size) {
      const score = (a: Airline) =>
        a.hubs.includes(o) || a.hubs.includes(d) ? 0 : a.regions.some((x) => routeRegions.has(x)) ? 1 : a.regions.includes("global") ? 2 : 3;
      r = [...r].sort((a, b) => score(a) - score(b));
    }
    return r;
  }, [list, region, cat, q, routeRegions, o, d, onlyDirect]);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Airlines</h1>
        <p className="text-sm text-muted">
          Go straight to an airline&apos;s own search. Add a route and dates and every link opens pre-filled where the airline supports it.
        </p>
      </div>

      <div className="grid grid-cols-1 items-end gap-2 rounded-2xl border border-border bg-surface p-3 lg:grid-cols-[1fr_1fr_minmax(0,1.2fr)_auto]">
        <AirportInput value={from} onChange={setFrom} placeholder="From (optional)" />
        <AirportInput value={to} onChange={setTo} placeholder="To (optional)" />
        <DateRangeField
          start={depart}
          end={oneWay ? undefined : ret}
          range={!oneWay}
          onChange={(s, e) => {
            setDepart(s);
            if (e) setRet(e);
          }}
        />
        <Segmented
          size="sm"
          value={oneWay ? "ow" : "rt"}
          onChange={(v) => setOneWay(v === "ow")}
          options={[
            { value: "rt", label: "Round trip" },
            { value: "ow", label: "One way" },
          ]}
        />
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        <Chip on={region === "all"} onClick={() => setRegion("all")}>
          All regions
        </Chip>
        {REGIONS.map((r) => (
          <Chip key={r.id} on={region === r.id} onClick={() => setRegion(r.id)}>
            {r.label}
          </Chip>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Segmented
          size="sm"
          value={cat}
          onChange={setCat}
          options={[
            { value: "all", label: "All" },
            { value: "low_cost", label: "Budget" },
            { value: "full_service", label: "Full service" },
            { value: "regional", label: "Regional" },
          ]}
        />
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-2 size-4 text-muted" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search airlines or tags"
            className="h-8 w-56 rounded-lg border border-border bg-surface pl-8 pr-2 text-sm outline-none focus:border-accent"
          />
        </div>
        <Switch checked={onlyDirect} onChange={setOnlyDirect} label={<span className="text-xs">Only airlines FlightScout searches directly</span>} />
        <span className="text-xs text-muted">{shown.length} airlines</span>
      </div>

      {!list ? (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 9 }).map((_, i) => (
            <div key={i} className="h-36 animate-pulse rounded-2xl bg-surface-2" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3">
          {shown.map((a) => (
            <AirlineCard key={a.iata + a.name} a={a} route={route} />
          ))}
        </div>
      )}
    </div>
  );
}

function Chip({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "h-7 rounded-full border px-3 text-xs transition-colors",
        on ? "border-transparent bg-fg text-bg" : "border-border text-muted hover:border-border-strong hover:text-fg",
      )}
    >
      {children}
    </button>
  );
}

function AirlineCard({ a, route }: { a: Airline; route: { origin: string; destination: string; depart: string; ret: string | null } | null }) {
  const [url, prefilled] = airlineLink(a, route);
  return (
    <div className="flex flex-col gap-2 rounded-2xl border border-border bg-surface p-3">
      <div className="flex items-center gap-3">
        <AirlineLogo code={a.iata} name={a.name} className="size-10" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="truncate font-medium">{a.name}</span>
            <span className="font-mono text-xs text-muted">{a.iata}</span>
          </div>
          <div className="text-xs text-muted">
            {CATEGORY_LABEL[a.category]}
            {a.alliance && ` · ${a.alliance === "star" ? "Star Alliance" : a.alliance === "oneworld" ? "oneworld" : "SkyTeam"}`}
            {a.hubs.length > 0 && ` · ${a.hubs.slice(0, 3).join(", ")}`}
          </div>
          {DIRECT[a.iata] === "everywhere" ? (
            <div className="mt-0.5 text-[11px] font-medium text-good" title="FlightScout reads this airline's own fares on every search">
              Included in FlightScout searches
            </div>
          ) : DIRECT[a.iata] === "local" ? (
            <div
              className="mt-0.5 text-[11px] font-medium text-info"
              title="FlightScout reads this airline's own fares when searches run on your computer (local runner). Otherwise its flights come through Google Flights and the booking sites."
            >
              Included in local FlightScout searches
            </div>
          ) : null}
        </div>
      </div>
      {a.tags.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {a.tags.slice(0, 5).map((t) => (
            <span key={t} className="rounded-full bg-surface-2 px-2 py-0.5 text-[11px] text-muted">
              {t}
            </span>
          ))}
        </div>
      )}
      {a.notes && <p className="line-clamp-2 text-xs text-muted">{a.notes}</p>}
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className="mt-auto inline-flex h-8 items-center justify-center gap-1.5 rounded-full border border-border-strong text-sm font-medium hover:bg-surface-2"
        title={route && !prefilled ? "This airline doesn't support pre-filled links, so this opens its search page" : undefined}
      >
        {route && prefilled ? `Search ${route.origin} to ${route.destination}` : `Open ${a.name}`}
        <ExternalLink className="size-3.5 text-muted" />
      </a>
    </div>
  );
}
