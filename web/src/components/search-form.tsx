"use client";
import { ArrowLeftRight, Search, Sparkles } from "lucide-react";
import { AirportInput, PlaceChips } from "./airport-input";
import { useApp } from "./app-context";
import { DateRangeField } from "./date-picker";
import { Button, Field, Segmented, Select, Switch } from "./ui";
import { addDays, dayDiff, isoDate } from "@/lib/format";
import type { Source } from "@/lib/types";

export type SearchForm = {
  from: string[];
  to: string[];
  tripType: "roundtrip" | "oneway";
  depart: string;
  ret: string;
  flex: number; // departure: +/- days
  retFlex: number; // return: +/- days
  cabin: "economy" | "premium" | "business" | "first";
  adults: number;
  stops: string;
  currency: string;
  sources: Source[];
  smart: boolean;
  nearby: number;
};

export function defaultForm(currency: string, origins: string[] = []): SearchForm {
  const d = addDays(isoDate(new Date()), 14);
  return {
    from: origins,
    to: [],
    tripType: "roundtrip",
    depart: d,
    ret: addDays(d, 7),
    flex: 0,
    retFlex: 0,
    cabin: "economy",
    adults: 1,
    stops: "any",
    currency,
    sources: ["google", "kiwi", "volaris"],
    smart: false,
    nearby: 0,
  };
}

export function formToParams(f: SearchForm) {
  const p = new URLSearchParams({
    from: f.from.join(","),
    to: f.to.join(","),
    d: f.depart,
    tt: f.tripType,
    cabin: f.cabin,
    adults: String(f.adults),
    stops: f.stops,
    cur: f.currency,
    src: f.sources.join(","),
    flex: String(f.flex),
    rflex: String(f.retFlex),
  });
  if (f.tripType === "roundtrip") p.set("r", f.ret);
  if (f.smart) p.set("smart", "1");
  if (f.nearby) p.set("near", String(f.nearby));
  return p;
}

export function paramsToForm(p: URLSearchParams, base: SearchForm): SearchForm {
  const list = (k: string) => (p.get(k) ? p.get(k)!.split(",").filter(Boolean) : undefined);
  return {
    ...base,
    from: list("from") ?? base.from,
    to: list("to") ?? base.to,
    depart: p.get("d") ?? base.depart,
    ret: p.get("r") ?? base.ret,
    tripType: (p.get("tt") as SearchForm["tripType"]) ?? (p.get("r") ? "roundtrip" : p.get("d") ? "oneway" : base.tripType),
    cabin: (p.get("cabin") as SearchForm["cabin"]) ?? base.cabin,
    adults: Number(p.get("adults") ?? base.adults),
    stops: p.get("stops") ?? base.stops,
    currency: p.get("cur") ?? base.currency,
    sources: (list("src") as Source[]) ?? base.sources,
    flex: Number(p.get("flex") ?? base.flex),
    retFlex: Number(p.get("rflex") ?? p.get("flex") ?? base.retFlex),
    smart: p.get("smart") === "1",
    nearby: Number(p.get("near") ?? base.nearby),
  };
}

const OPT = "h-8 rounded-lg border-transparent bg-surface-2 text-xs hover:bg-surface-3";

export function SearchFormView({
  value,
  onChange,
  onSubmit,
  busy,
}: {
  value: SearchForm;
  onChange: (f: SearchForm) => void;
  onSubmit: () => void;
  busy?: boolean;
}) {
  const f = value;
  const set = (p: Partial<SearchForm>) => onChange({ ...f, ...p });
  const { currency } = useApp();
  const rt = f.tripType === "roundtrip";
  const prices = f.from.length && f.to.length ? { from: f.from, to: f.to, tripDays: rt ? dayDiff(f.depart, f.ret) : null, currency } : null;

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
      className="rounded-2xl border border-border bg-surface p-3 shadow-[var(--shadow)] sm:p-4"
    >
      <div className="mb-3 flex flex-wrap items-center gap-1.5">
        <Segmented
          size="sm"
          value={f.tripType}
          onChange={(tripType) => set({ tripType, ret: tripType === "roundtrip" && f.ret <= f.depart ? addDays(f.depart, 7) : f.ret })}
          options={[
            { value: "roundtrip", label: "Round trip" },
            { value: "oneway", label: "One way" },
          ]}
        />
        <Select className={OPT} value={f.adults} onChange={(e) => set({ adults: Number(e.target.value) })} aria-label="Passengers">
          {[1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => (
            <option key={n} value={n}>
              {n} {n > 1 ? "adults" : "adult"}
            </option>
          ))}
        </Select>
        <Select className={OPT} value={f.cabin} onChange={(e) => set({ cabin: e.target.value as SearchForm["cabin"] })} aria-label="Cabin">
          <option value="economy">Economy</option>
          <option value="premium">Premium economy</option>
          <option value="business">Business</option>
          <option value="first">First</option>
        </Select>
        <Select className={OPT} value={f.stops} onChange={(e) => set({ stops: e.target.value })} aria-label="Stops">
          <option value="any">Any stops</option>
          <option value="0">Nonstop</option>
          <option value="1">1 stop or fewer</option>
          <option value="2">2 stops or fewer</option>
        </Select>
        <Select className={OPT} value={f.nearby} onChange={(e) => set({ nearby: Number(e.target.value) })} aria-label="Nearby airports">
          <option value={0}>Exact airports</option>
          <option value={50}>+ airports within 50 km</option>
          <option value={100}>+ airports within 100 km</option>
          <option value={150}>+ airports within 150 km</option>
          <option value={250}>+ airports within 250 km</option>
        </Select>
        <div className="ml-auto">
          <Switch
            checked={f.smart}
            onChange={(smart) => set({ smart })}
            label={
              <span className="flex items-center gap-1.5 text-xs" title="Also build cheaper routes from separate tickets through hubs (split tickets, stopovers, nested round trips)">
                <Sparkles className="size-3.5 text-info" /> Smarter routes
              </span>
            }
          />
        </div>
      </div>
      <div className="grid grid-cols-1 items-end gap-2 lg:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)_minmax(0,1.15fr)_auto]">
        <Field label="From">
          <AirportInput value={f.from} onChange={(from) => set({ from })} placeholder="Where from?" />
        </Field>
        <button
          type="button"
          onClick={() => set({ from: f.to, to: f.from })}
          className="mb-1 hidden size-9 place-items-center rounded-full border border-border text-muted hover:bg-surface-2 hover:text-fg lg:grid"
          aria-label="Swap origin and destination"
          title="Swap"
        >
          <ArrowLeftRight className="size-4" />
        </button>
        <Field label="To">
          <AirportInput value={f.to} onChange={(to) => set({ to })} placeholder="Anywhere (explore)" />
        </Field>
        <div className="min-w-0">
          <DateRangeField
            start={f.depart}
            end={rt ? f.ret : undefined}
            range={rt}
            prices={prices}
            onChange={(depart, ret) => set({ depart, ret: rt ? (ret ?? f.ret) : f.ret })}
          />
        </div>
        <Button type="submit" variant="primary" className="h-11 px-5" loading={busy} disabled={!f.from.length || !f.to.length}>
          <Search className="size-4" /> Search
        </Button>
      </div>
      <div className="mt-2 flex flex-wrap items-center justify-end gap-x-4 gap-y-1 text-xs text-muted">
        <span className="mr-auto" />
        <FlexPick label="Departure" value={f.flex} onChange={(flex) => set({ flex })} />
        {rt && <FlexPick label="Return" value={f.retFlex} onChange={(retFlex) => set({ retFlex })} />}
      </div>
      <div className="mt-2 grid grid-cols-1 gap-2 lg:grid-cols-2">
        <PlaceChips onPick={(c) => set({ from: [...new Set([...f.from, ...c])] })} />
        <PlaceChips onPick={(c) => set({ to: [...new Set([...f.to, ...c])] })} />
      </div>
    </form>
  );
}

const FLEX = [0, 1, 2, 3, 7];

// "Departure: exact | ±1 | ±2 | ±3 | ±7 days", one per date so it's clear
// which side is flexible.
function FlexPick({ label, value, onChange }: { label: string; value: number; onChange: (n: number) => void }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span>{label}</span>
      <span className="inline-flex rounded-full bg-surface-2 p-0.5">
        {FLEX.map((n) => (
          <button
            key={n}
            type="button"
            onClick={() => onChange(n)}
            className={
              "h-6 rounded-full px-2 tabular-nums transition-colors " +
              (value === n ? "bg-surface text-fg shadow-sm ring-1 ring-border" : "text-muted hover:text-fg")
            }
            title={n ? `Also search ${n} day${n > 1 ? "s" : ""} before and after` : "Only this date"}
          >
            {n ? `±${n}` : "exact"}
          </button>
        ))}
      </span>
    </span>
  );
}
