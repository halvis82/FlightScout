"use client";
import { ArrowLeftRight, Search, Sparkles } from "lucide-react";
import { AirportInput, PlaceChips } from "./airport-input";
import { useApp } from "./app-context";
import { Button, Field, Input, Segmented, Select, Switch } from "./ui";
import { addDays, isoDate } from "@/lib/format";
import { CURRENCIES, type Source } from "@/lib/types";

export type SearchForm = {
  from: string[];
  to: string[];
  tripType: "roundtrip" | "oneway";
  depart: string;
  ret: string;
  flex: number;
  cabin: "economy" | "premium" | "business" | "first";
  adults: number;
  stops: string;
  currency: string;
  sources: Source[];
  smart: boolean;
  nearby: number;
};

export function defaultForm(currency: string, origins: string[] = []): SearchForm {
  const d = addDays(isoDate(new Date()), 30);
  return {
    from: origins,
    to: [],
    tripType: "roundtrip",
    depart: d,
    ret: addDays(d, 7),
    flex: 0,
    cabin: "economy",
    adults: 1,
    stops: "any",
    currency,
    sources: ["google", "kiwi"],
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
    smart: p.get("smart") === "1",
    nearby: Number(p.get("near") ?? base.nearby),
  };
}

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
  const today = isoDate(new Date());

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
      className="rounded-xl border border-border bg-surface p-3 shadow-[var(--shadow)] sm:p-4"
    >
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Segmented
          size="sm"
          value={f.tripType}
          onChange={(tripType) => set({ tripType })}
          options={[
            { value: "roundtrip", label: "Round trip" },
            { value: "oneway", label: "One way" },
          ]}
        />
        <Select className="h-7 text-xs" value={f.cabin} onChange={(e) => set({ cabin: e.target.value as SearchForm["cabin"] })}>
          <option value="economy">Economy</option>
          <option value="premium">Premium economy</option>
          <option value="business">Business</option>
          <option value="first">First</option>
        </Select>
        <Select className="h-7 text-xs" value={f.adults} onChange={(e) => set({ adults: Number(e.target.value) })}>
          {[1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => (
            <option key={n} value={n}>
              {n} adult{n > 1 ? "s" : ""}
            </option>
          ))}
        </Select>
        <Select className="h-7 text-xs" value={f.stops} onChange={(e) => set({ stops: e.target.value })}>
          <option value="any">Any stops</option>
          <option value="0">Nonstop only</option>
          <option value="1">1 stop max</option>
          <option value="2">2 stops max</option>
        </Select>
        <Select className="h-7 text-xs" value={f.nearby} onChange={(e) => set({ nearby: Number(e.target.value) })} title="Also search airports near your origin and destination">
          <option value={0}>Exact airports</option>
          <option value={50}>+ nearby 50 km</option>
          <option value={100}>+ nearby 100 km</option>
          <option value={150}>+ nearby 150 km</option>
          <option value={250}>+ nearby 250 km</option>
        </Select>
        <Select className="h-7 text-xs" value={f.currency} onChange={(e) => set({ currency: e.target.value })} title={`Display currency is ${currency}`}>
          {CURRENCIES.map((c) => (
            <option key={c}>{c}</option>
          ))}
        </Select>
        <div className="ml-auto flex items-center gap-2 text-xs">
          {(["google", "kiwi"] as Source[]).map((s) => (
            <label key={s} className="flex items-center gap-1 text-muted">
              <input
                type="checkbox"
                className="accent-[var(--accent)]"
                checked={f.sources.includes(s)}
                onChange={(e) => set({ sources: e.target.checked ? [...f.sources, s] : f.sources.filter((x) => x !== s) })}
              />
              {s === "google" ? "Google Flights" : "Kiwi.com"}
            </label>
          ))}
        </div>
      </div>
      <div className="grid grid-cols-1 gap-2 md:grid-cols-[1fr_auto_1fr_150px_150px_110px]">
        <Field label="From">
          <AirportInput value={f.from} onChange={(from) => set({ from })} placeholder="Where from?" />
        </Field>
        <button
          type="button"
          onClick={() => set({ from: f.to, to: f.from })}
          className="hidden self-end rounded-md p-2 text-muted hover:bg-surface-2 hover:text-fg md:block"
          aria-label="Swap"
          title="Swap"
        >
          <ArrowLeftRight className="size-4" />
        </button>
        <Field label="To">
          <AirportInput value={f.to} onChange={(to) => set({ to })} placeholder="Where to?" />
        </Field>
        <Field label="Depart">
          <Input
            type="date"
            value={f.depart}
            min={today}
            onChange={(e) => set({ depart: e.target.value, ret: f.ret < e.target.value ? addDays(e.target.value, 7) : f.ret })}
          />
        </Field>
        <Field label="Return">
          <Input type="date" value={f.ret} min={f.depart} disabled={f.tripType === "oneway"} onChange={(e) => set({ ret: e.target.value })} />
        </Field>
        <Field label="Flexible">
          <Select value={f.flex} onChange={(e) => set({ flex: Number(e.target.value) })}>
            <option value={0}>Exact</option>
            <option value={1}>± 1 day</option>
            <option value={2}>± 2 days</option>
            <option value={3}>± 3 days</option>
            <option value={5}>± 5 days</option>
            <option value={7}>± 7 days</option>
          </Select>
        </Field>
      </div>
      <div className="mt-2 grid grid-cols-1 gap-2 md:grid-cols-2">
        <PlaceChips onPick={(c) => set({ from: [...new Set([...f.from, ...c])] })} />
        <PlaceChips onPick={(c) => set({ to: [...new Set([...f.to, ...c])] })} />
      </div>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-3">
        <Switch
          checked={f.smart}
          onChange={(smart) => set({ smart })}
          label={
            <span className="flex items-center gap-1.5">
              <Sparkles className="size-3.5 text-info" />
              Find smarter routes
              <span className="hidden text-xs text-muted sm:inline">split tickets, stopovers and nested round trips through hubs</span>
            </span>
          }
        />
        <Button type="submit" variant="primary" loading={busy} disabled={!f.from.length || !f.to.length || !f.sources.length}>
          <Search className="size-4" /> Search flights
        </Button>
      </div>
    </form>
  );
}
