"use client";
import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp, Plus, Route, Trash2 } from "lucide-react";
import { AirportInput, PlaceChips } from "@/components/airport-input";
import { useApp } from "@/components/app-context";
import { ResultsView } from "@/components/results-view";
import { RouteMap, type MapArc, type MapPoint } from "@/components/route-map";
import { Button, Card, Empty, ErrorNote, Field, Input, PageHeader, Select, Spinner, Switch } from "@/components/ui";
import { api } from "@/lib/client";
import { addDays, isoDate } from "@/lib/format";
import { expandCodes } from "@/lib/airports-client";
import { CURRENCIES, type PlanResult } from "@/lib/types";

type Stop = { place: string[]; min: number; max: number };

export default function TripBuilder() {
  const { settings, currency } = useApp();
  const [start, setStart] = useState<string[] | null>(null);
  const [end, setEnd] = useState<string[]>([]);
  const [stops, setStops] = useState<Stop[]>([{ place: [], min: 2, max: 4 }]);
  const [from, setFrom] = useState(() => addDays(isoDate(new Date()), 30));
  const [to, setTo] = useState(() => addDays(isoDate(new Date()), 37));
  const [maxDays, setMaxDays] = useState<string>("");
  const [keepOrder, setKeepOrder] = useState(false);
  const [cur, setCur] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [res, setRes] = useState<PlanResult | null>(null);

  const home = useMemo(() => start ?? settings?.defaultOrigins.slice(0, 1) ?? [], [start, settings]);
  const currencyUsed = cur ?? currency;
  const setStop = (i: number, p: Partial<Stop>) => setStops((s) => s.map((x, j) => (j === i ? { ...x, ...p } : x)));
  const move = (i: number, d: number) =>
    setStops((s) => {
      const n = [...s];
      [n[i], n[i + d]] = [n[i + d], n[i]];
      return n;
    });

  const preview = useMemo(() => {
    const seq = [home[0], ...stops.map((s) => s.place[0]), (end[0] ?? home[0])].filter(Boolean) as string[];
    const arcs: MapArc[] = seq.slice(1).map((c, i) => ({ from: seq[i], to: c, tone: "muted", dashed: !keepOrder }));
    const points: MapPoint[] = seq.map((c, i) => ({ code: c, tone: i === 0 || i === seq.length - 1 ? "origin" : "dest", label: i === 0 || i === seq.length - 1 ? c : `${i}. ${c}` }));
    return { arcs, points, key: seq.join() };
  }, [home, stops, end, keepOrder]);

  async function run() {
    setBusy(true);
    setErr(null);
    setRes(null);
    try {
      const r = await api<PlanResult>("/trip", {
        body: {
          start: expandCodes(home)[0],
          end: end.length ? expandCodes(end)[0] : null,
          stops: stops.filter((s) => s.place.length).map((s) => ({ place: s.place[0], min_nights: s.min, max_nights: Math.max(s.min, s.max) })),
          earliest_departure: from,
          latest_departure: to,
          max_trip_days: maxDays ? Number(maxDays) : null,
          keep_order: keepOrder,
          currency: currencyUsed,
        },
      });
      setRes(r);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const ready = home.length > 0 && stops.some((s) => s.place.length);

  return (
    <div className="space-y-4">
      <PageHeader
        title="Trip builder"
        sub="Plan a multi city trip from scratch. FlightScout picks the order, dates and one way tickets that make the whole trip cheapest within your limits."
      />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_380px]">
        <Card className="space-y-3 p-4">
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <Field label="Start from">
              <AirportInput value={home} onChange={(v) => setStart(v)} single placeholder="Home airport" />
              <PlaceChips kinds={["home", "frequent"]} onPick={(c) => setStart(c.slice(0, 1))} />
            </Field>
            <Field label="End at" hint="Leave empty to return to the start">
              <AirportInput value={end} onChange={setEnd} single placeholder="Same as start" />
            </Field>
          </div>
          <div className="space-y-2">
            <div className="text-[11px] font-medium uppercase tracking-wide text-muted">Places to visit</div>
            {stops.map((s, i) => (
              <div key={i} className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-2 sm:grid-cols-[auto_minmax(0,1fr)_150px_auto]">
                <span className="mt-2 w-5 text-right text-sm text-muted">{i + 1}.</span>
                <div>
                  <AirportInput value={s.place} onChange={(place) => setStop(i, { place })} single placeholder="City or airport" />
                  {i === stops.length - 1 && <PlaceChips kinds={["interested", "frequent"]} onPick={(c) => setStop(i, { place: c.slice(0, 1) })} />}
                </div>
                <div className="col-start-2 flex items-center gap-1 text-sm text-muted sm:col-start-auto">
                  <Input type="number" min={0} className="w-14" value={s.min} onChange={(e) => setStop(i, { min: Number(e.target.value) })} aria-label="Min nights" />
                  to
                  <Input type="number" min={s.min} className="w-14" value={s.max} onChange={(e) => setStop(i, { max: Number(e.target.value) })} aria-label="Max nights" />
                  <span className="text-xs">nights</span>
                </div>
                <div className="row-start-1 flex gap-0.5 sm:row-start-auto">
                  <button disabled={i === 0} onClick={() => move(i, -1)} className="rounded p-1.5 text-muted hover:bg-surface-2 disabled:opacity-30" aria-label="Move up">
                    <ArrowUp className="size-3.5" />
                  </button>
                  <button disabled={i === stops.length - 1} onClick={() => move(i, 1)} className="rounded p-1.5 text-muted hover:bg-surface-2 disabled:opacity-30" aria-label="Move down">
                    <ArrowDown className="size-3.5" />
                  </button>
                  <button onClick={() => setStops((x) => x.filter((_, j) => j !== i))} className="rounded p-1.5 text-muted hover:bg-bad-soft hover:text-bad" aria-label="Remove">
                    <Trash2 className="size-3.5" />
                  </button>
                </div>
              </div>
            ))}
            <Button size="sm" onClick={() => setStops((s) => [...s, { place: [], min: 2, max: 4 }])} disabled={stops.length >= 8}>
              <Plus className="size-3.5" /> Add a place
            </Button>
          </div>
          <div className="grid grid-cols-2 gap-2 border-t border-border pt-3 sm:grid-cols-4">
            <Field label="Leave between">
              <Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
            </Field>
            <Field label="and">
              <Input type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} />
            </Field>
            <Field label="Max trip days">
              <Input type="number" min={1} value={maxDays} placeholder="No limit" onChange={(e) => setMaxDays(e.target.value)} />
            </Field>
            <Field label="Currency">
              <Select value={currencyUsed} onChange={(e) => setCur(e.target.value)}>
                {CURRENCIES.map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </Select>
            </Field>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <Switch checked={keepOrder} onChange={setKeepOrder} label="Keep this order" />
            <Button variant="primary" onClick={run} loading={busy} disabled={!ready}>
              <Route className="size-4" /> Build trip
            </Button>
          </div>
        </Card>
        <RouteMap arcs={preview.arcs} points={preview.points} className="h-64 lg:h-auto lg:min-h-[420px]" fitKey={preview.key} />
      </div>
      {busy && (
        <div className="flex items-center gap-2 text-sm text-muted">
          <Spinner /> Pricing every leg across the date window. Multi city trips can take a minute or two.
        </div>
      )}
      {err && <ErrorNote>{err}</ErrorNote>}
      {res && (res.trips.length ? <ResultsView trips={res.trips} errors={res.errors} plan={res} /> : <Empty title="No complete trip found">Try a wider date window, more flexible nights, or letting FlightScout reorder the stops.</Empty>)}
    </div>
  );
}
