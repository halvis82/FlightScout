"use client";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
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

// The trip is kept in the URL (?s=SAN&p=CDG:2-4,FCO:3-5&f=...&t=...) so a
// built trip survives a reload and can be shared. Anything invalid falls back
// to the defaults.
const CODE = /^[A-Z]{3,4}$/;
function fromParams(q: URLSearchParams) {
  const today = isoDate(new Date());
  const code = (v: string | null) => (v && CODE.test(v.toUpperCase()) ? [v.toUpperCase()] : null);
  const date = (v: string | null) => (v && /^\d{4}-\d{2}-\d{2}$/.test(v) && v >= today ? v : null);
  const nights = (v: string | undefined, d: number) => (v && /^\d{1,2}$/.test(v) ? Number(v) : d);
  const stops = (q.get("p") ?? "")
    .split(",")
    .map((x) => x.match(/^([A-Za-z]{3,4})(?::(\d{1,2})(?:-(\d{1,2}))?)?$/))
    .filter((m): m is RegExpMatchArray => Boolean(m))
    .slice(0, 8)
    .map((m) => {
      const min = nights(m[2], 2);
      return { place: [m[1].toUpperCase()], min, max: Math.max(min, nights(m[3], Math.max(min, 4))) };
    });
  const from = date(q.get("f")) ?? addDays(today, 30);
  const to = date(q.get("t"));
  const max = q.get("m");
  const cur = q.get("c")?.toUpperCase() ?? null;
  return {
    start: code(q.get("s")),
    end: code(q.get("e")) ?? [],
    stops: stops.length ? stops : [{ place: [], min: 2, max: 4 }],
    from,
    to: to && to >= from ? to : addDays(from, 7),
    maxDays: max && /^\d{1,3}$/.test(max) ? max : "",
    keepOrder: q.get("o") === "1",
    cur: cur && (CURRENCIES as readonly string[]).includes(cur) ? cur : null,
    ready: stops.length > 0 && Boolean(code(q.get("s"))),
  };
}

export default function TripBuilderPage() {
  return (
    <Suspense>
      <TripBuilder />
    </Suspense>
  );
}

function TripBuilder() {
  const { settings, currency } = useApp();
  const router = useRouter();
  const params = useSearchParams();
  const [init] = useState(() => fromParams(params));
  const [start, setStart] = useState<string[] | null>(init.start);
  const [end, setEnd] = useState<string[]>(init.end);
  const [stops, setStops] = useState<Stop[]>(init.stops);
  const [from, setFrom] = useState(init.from);
  const [to, setTo] = useState(init.to);
  const [maxDays, setMaxDays] = useState<string>(init.maxDays);
  const [keepOrder, setKeepOrder] = useState(init.keepOrder);
  const [cur, setCur] = useState<string | null>(init.cur);
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
    const q = new URLSearchParams();
    if (home[0]) q.set("s", home[0]);
    if (end[0]) q.set("e", end[0]);
    q.set("p", stops.filter((x) => x.place.length).map((x) => `${x.place[0]}:${x.min}-${Math.max(x.min, x.max)}`).join(","));
    q.set("f", from);
    q.set("t", to);
    if (maxDays) q.set("m", maxDays);
    if (keepOrder) q.set("o", "1");
    if (cur) q.set("c", cur);
    router.replace(`/trip?${q.toString()}`, { scroll: false });
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

  // opened from a link or a reload: build that trip again
  const auto = useRef(init.ready);
  useEffect(() => {
    if (!auto.current) return;
    auto.current = false;
    run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
