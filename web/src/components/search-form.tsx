"use client";
import { ArrowLeftRight, Search, Sparkles } from "lucide-react";
import { AirportInput, PlaceChips } from "./airport-input";
import { useApp } from "./app-context";
import { DateRangeField } from "./date-picker";
import { Button, Field, Segmented, Select, Switch } from "./ui";
import { addDays, dayDiff, isoDate } from "@/lib/format";
import type { Source } from "@/lib/types";
import { preset } from "@/lib/presets";

export type LegFlex = number | "by"; // ±days, or "arrive by this date"
export type MultiLeg = { to: string[]; date: string; flex: LegFlex };

export type SearchForm = {
  from: string[];
  to: string[];
  tripType: "roundtrip" | "oneway" | "multicity";
  legs: MultiLeg[];
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
    legs: [],
    depart: d,
    ret: addDays(d, 7),
    flex: 0,
    retFlex: 0,
    cabin: "economy",
    adults: 1,
    stops: "any",
    currency,
    sources: ["google", "kiwi", "volaris"],
    smart: true,
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
  if (f.tripType === "multicity") p.set("ml", JSON.stringify(f.legs));
  p.set("smart", f.smart ? "1" : "0");
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
    smart: p.has("smart") ? p.get("smart") === "1" : base.smart,
    legs: (() => {
      try {
        return p.get("ml") ? (JSON.parse(p.get("ml")!) as MultiLeg[]) : base.legs;
      } catch {
        return base.legs;
      }
    })(),
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
          onChange={(tripType) =>
            set({
              tripType,
              ret: tripType === "roundtrip" && f.ret <= f.depart ? addDays(f.depart, 7) : f.ret,
              legs:
                tripType === "multicity" && !f.legs.length
                  ? [
                      { to: f.to, date: f.depart, flex: 0 },
                      { to: f.from, date: f.ret > f.depart ? f.ret : addDays(f.depart, 7), flex: 0 },
                    ]
                  : f.legs,
            })
          }
          options={[
            { value: "roundtrip", label: "Round trip" },
            { value: "oneway", label: "One way" },
            { value: "multicity", label: "Multi-city" },
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
        <div className={f.tripType === "multicity" ? "hidden" : "ml-auto"}>
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
      {f.tripType === "multicity" ? (
        <MultiCityLegs f={f} set={set} busy={busy} />
      ) : (
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
        <Button type="submit" variant="primary" className="h-11 px-5" loading={busy} disabled={!f.from.length}>
          <Search className="size-4" /> {f.to.length ? "Search" : "Explore"}
        </Button>
      </div>
      )}
      {f.tripType !== "multicity" && (
      <div className="mt-2 flex flex-wrap items-center justify-end gap-x-4 gap-y-1 text-xs text-muted">
        <span className="mr-auto inline-flex items-center gap-1">
          {[
            { key: "oneway", label: "One flight" },
            { key: "weekend", label: "Weekend" },
            { key: "week", label: "1 week" },
            { key: "twoweeks", label: "2 weeks" },
          ].map((o) => {
            const nights = rt ? dayDiff(f.depart, f.ret) : -1;
            const on =
              (o.key === "oneway" && !rt) ||
              (o.key === "weekend" && rt && nights >= 2 && nights <= 3 && new Date(f.depart + "T12:00").getDay() >= 4) ||
              (o.key === "week" && rt && nights === 7) ||
              (o.key === "twoweeks" && rt && nights === 14);
            return (
              <button
                key={o.key}
                type="button"
                onClick={() => set(preset(o.key, f))}
                className={
                  "h-6 rounded-full border px-2.5 transition-colors " +
                  (on ? "border-accent bg-accent-soft text-accent" : "border-border hover:border-border-strong hover:text-fg")
                }
              >
                {o.label}
              </button>
            );
          })}
        </span>
        <FlexPick label="Departure" value={f.flex} onChange={(flex) => set({ flex })} />
        {rt && <FlexPick label="Return" value={f.retFlex} onChange={(retFlex) => set({ retFlex })} />}
      </div>
      )}
      <div className="mt-2 grid grid-cols-1 gap-2 lg:grid-cols-2">
        <PlaceChips current={f.from} onPick={(c) => set({ from: c })} />
        <PlaceChips current={f.to} onPick={(c) => set({ to: c })} />
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

function MultiCityLegs({ f, set, busy }: { f: SearchForm; set: (p: Partial<SearchForm>) => void; busy?: boolean }) {
  const legs = f.legs;
  const upd = (i: number, p: Partial<MultiLeg>) => set({ legs: legs.map((l, j) => (j === i ? { ...l, ...p } : l)) });
  const ready = f.from.length > 0 && legs.length > 0 && legs.every((l) => l.to.length);
  return (
    <div className="space-y-2">
      <Field label="Start from">
        <AirportInput value={f.from} onChange={(from) => set({ from })} placeholder="Where does the trip start?" />
      </Field>
      {legs.map((l, i) => {
        const fromCodes = i === 0 ? f.from : legs[i - 1].to;
        return (
          <div key={i} className="grid grid-cols-1 items-end gap-2 rounded-xl border border-border p-2 lg:grid-cols-[110px_minmax(0,1fr)_minmax(0,0.8fr)_auto_auto]">
            <div className="pb-2 text-xs text-muted">
              <div className="font-medium text-fg">Flight {i + 1}</div>
              from {fromCodes.join(", ") || "..."}
            </div>
            <Field label="To">
              <AirportInput value={l.to} onChange={(to) => upd(i, { to })} placeholder="Next stop" />
            </Field>
            <DateRangeField
              start={l.date}
              range={false}
              labels={[l.flex === "by" ? "Arrive by" : "Depart", ""]}
              min={i > 0 ? legs[i - 1].date : undefined}
              onChange={(date) => upd(i, { date })}
              prices={fromCodes.length && l.to.length ? { from: fromCodes, to: l.to, tripDays: null, currency: f.currency } : null}
            />
            <Select
              className="h-11 w-44 text-sm"
              aria-label={`Flexibility for flight ${i + 1}`}
              value={String(l.flex)}
              onChange={(e) => upd(i, { flex: e.target.value === "by" ? "by" : Number(e.target.value) })}
            >
              <option value="0">Exact date</option>
              <option value="1">± 1 day</option>
              <option value="2">± 2 days</option>
              <option value="3">± 3 days</option>
              <option value="7">± 7 days</option>
              <option value="by">Arrive by this date</option>
            </Select>
            <button
              type="button"
              onClick={() => set({ legs: legs.filter((_, j) => j !== i) })}
              className="mb-1 grid size-9 place-items-center rounded-full text-muted hover:bg-surface-2 hover:text-fg"
              aria-label={`Remove flight ${i + 1}`}
              disabled={legs.length <= 1}
            >
              ×
            </button>
          </div>
        );
      })}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Button
          type="button"
          size="sm"
          onClick={() => {
            const last = legs[legs.length - 1];
            set({ legs: [...legs, { to: [], date: addDays(last?.date ?? f.depart, 4), flex: 2 }] });
          }}
        >
          + Add flight
        </Button>
        <Button type="submit" variant="primary" className="h-11 px-5" loading={busy} disabled={!ready}>
          <Search className="size-4" /> Search
        </Button>
      </div>
    </div>
  );
}

