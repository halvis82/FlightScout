"use client";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Eye, Sparkles } from "lucide-react";
import { useApp } from "@/components/app-context";
import { ExplorePanel } from "@/components/explore-panel";
import { ResultsView, mergeTrips } from "@/components/results-view";
import { SearchFormView, defaultForm, formToParams, paramsToForm, type SearchForm } from "@/components/search-form";
import { useWatchDialog } from "@/components/watch-dialog";
import { Button, Empty, ErrorNote, Spinner } from "@/components/ui";
import { api } from "@/lib/client";
import { airport, expandCodes } from "@/lib/airports-client";
import { RouteMap } from "@/components/route-map";
import { addDays, dayDiff } from "@/lib/format";
import type { PlanResult, SearchQuery, SearchResult } from "@/lib/types";

export default function Page() {
  return (
    <Suspense>
      <SearchPage />
    </Suspense>
  );
}

// The search page keeps its state when you switch tabs (module memory) and
// across reloads of the same browser tab (sessionStorage).
type Saved = { form: SearchForm | null; result: SearchResult | null; plan: PlanResult | null };
const KEY = "fs.search.v1";
let saved: Saved | null = null;
function loadSaved(): Saved {
  if (saved) return saved;
  try {
    const raw = typeof window !== "undefined" ? sessionStorage.getItem(KEY) : null;
    saved = raw ? (JSON.parse(raw) as Saved) : { form: null, result: null, plan: null };
  } catch {
    saved = { form: null, result: null, plan: null };
  }
  return saved;
}
function persist(next: Saved) {
  saved = next;
  try {
    sessionStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    /* quota or private mode: memory copy is enough */
  }
}

function SearchPage() {
  const { settings, currency } = useApp();
  const router = useRouter();
  const params = useSearchParams();
  const hasQuery = Boolean(params.get("from"));
  const [edited, setForm] = useState<SearchForm | null>(() => (hasQuery ? null : loadSaved().form));
  // Until the user edits, the form comes from the URL (or their defaults).
  const form = edited ?? (settings ? paramsToForm(params, defaultForm(currency, settings.defaultOrigins)) : null);
  const [result, setResult] = useState<SearchResult | null>(() => (hasQuery ? null : loadSaved().result));
  const [plan, setPlan] = useState<PlanResult | null>(() => (hasQuery ? null : loadSaved().plan));
  useEffect(() => {
    if (edited || result || plan) persist({ form: edited, result, plan });
  }, [edited, result, plan]);
  const [busy, setBusy] = useState(false);
  const [planBusy, setPlanBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const autoRan = useRef(false);
  const watch = useWatchDialog();

  const run = useCallback(
    async (f0: SearchForm) => {
      setForm(f0);
      const f = { ...f0, currency };
      lastRun.current = JSON.stringify([f.from, f.to, f.depart, f.ret, f.tripType, f.flex, f.retFlex]);
      setErr(null);
      setResult(null);
      setPlan(null);
      setBusy(true);
      setElapsed(0);
      const t0 = Date.now();
      const timer = setInterval(() => setElapsed(Math.round((Date.now() - t0) / 1000)), 1000);
      router.replace(`/?${formToParams(f).toString()}`, { scroll: false });
      const q: SearchQuery = {
        origins: expandCodes(f.from),
        destinations: expandCodes(f.to),
        departure: f.depart,
        return_date: f.tripType === "roundtrip" ? f.ret : null,
        adults: f.adults,
        cabin: f.cabin,
        max_stops: f.stops === "any" ? null : Number(f.stops),
        currency: f.currency,
        sources: f.sources,
        departure_flex_days: f.flex,
        return_flex_days: f.tripType === "roundtrip" ? f.retFlex : 0,
        nearby_km: f.nearby,
      };
      const searchP = api<SearchResult>("/search", { body: q })
        .then(setResult)
        .catch((e) => setErr((e as Error).message))
        .finally(() => setBusy(false));
      let planP: Promise<void> = Promise.resolve();
      if (f.smart && settings) {
        setPlanBusy(true);
        const p = settings.planner;
        planP = api<PlanResult>("/plan", {
          body: {
            origins: q.origins,
            destinations: q.destinations,
            depart_start: addDays(f.depart, -f.flex),
            depart_end: addDays(f.depart, f.flex),
            return_start: q.return_date ? addDays(f.ret, -f.retFlex) : null,
            return_end: q.return_date ? addDays(f.ret, f.retFlex) : null,
            currency: f.currency,
            cabin: f.cabin,
            adults: f.adults,
            ...p,
          },
        })
          .then(setPlan)
          .catch((e) => setErr((x) => (x ? x + " · " : "") + `Smart routes: ${(e as Error).message}`))
          .finally(() => setPlanBusy(false));
      }
      await Promise.all([searchP, planP]);
      clearInterval(timer);
    },
    [router, settings, currency],
  );
  const lastRun = useRef<string | null>(null);

  // After a first search, changing dates (arrows or calendar) searches again.
  useEffect(() => {
    if (!form || !lastRun.current || !form.to.length || !form.from.length) return;
    const k = JSON.stringify([form.from, form.to, form.depart, form.ret, form.tripType, form.flex, form.retFlex]);
    if (k === lastRun.current) return;
    const t = setTimeout(() => run(form), 700);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form?.depart, form?.ret, form?.tripType, form?.flex, form?.retFlex]);

  // Auto run when opened with a full query in the URL (links from watches, history, CLI).
  useEffect(() => {
    if (form && !autoRan.current && params.get("from") && params.get("to") && params.get("d")) {
      autoRan.current = true;
      run(form);
    }
  }, [form, params, run]);

  if (!form)
    return (
      <div className="grid h-64 place-items-center text-muted">
        <Spinner />
      </div>
    );

  const trips = mergeTrips(result, plan);
  const hasResults = result || plan;

  return (
    <div className="space-y-4">
      <SearchFormView value={form} onChange={setForm} onSubmit={() => run(form)} busy={busy} />
      {(busy || planBusy) && (
        <div className="flex items-center gap-2 text-sm text-muted">
          <Spinner />
          {busy ? `Searching ${form.sources.join(" and ")}` : "Direct results ready."}
          {planBusy && (
            <span className="inline-flex items-center gap-1">
              <Sparkles className="size-3.5 text-info" /> Building smart routes through hubs. This can take a minute or two.
            </span>
          )}
          <span className="tabular-nums text-faint">{elapsed}s</span>
        </div>
      )}
      {err && <ErrorNote>{err}</ErrorNote>}
      {hasResults && (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="text-sm text-muted">
            {form.from.join("/")} to {form.to.join("/")} ·{" "}
            {form.tripType === "roundtrip" ? `${dayDiff(form.depart, form.ret)} nights` : "one way"}
          </div>
          <Button
            size="sm"
            onClick={() =>
              watch.open({
                origins: form.from,
                destinations: form.to,
                trip_type: form.tripType,
                depart_start: addDays(form.depart, -form.flex),
                depart_end: addDays(form.depart, form.flex),
                nights_min: form.tripType === "roundtrip" ? Math.max(0, dayDiff(form.depart, form.ret) - form.flex - form.retFlex) : null,
                nights_max: form.tripType === "roundtrip" ? dayDiff(form.depart, form.ret) + form.flex + form.retFlex : null,
                currency: form.currency,
                cabin: form.cabin,
                adults: form.adults,
                include_split: form.smart,
              }, trips)
            }
          >
            <Eye className="size-3.5" /> Watch this search
          </Button>
        </div>
      )}
      {!form.to.length && form.from.length > 0 && !hasResults && (
        <ExplorePanel
          origins={form.from}
          depart={form.depart}
          ret={form.ret}
          roundTrip={form.tripType === "roundtrip"}
          flex={form.flex}
          retFlex={form.retFlex}
          onPick={(d) => {
            const next: SearchForm = {
              ...form,
              to: [d.destination],
              depart: d.departure ?? form.depart,
              ret: d.return_date ?? form.ret,
              tripType: d.return_date ? "roundtrip" : form.tripType,
            };
            setForm(next);
            run(next);
          }}
        />
      )}
      {hasResults ? (
        <ResultsView
          trips={trips}
          query={result?.query ?? { origins: form.from, destinations: form.to }}
          errors={{ ...(result?.errors ?? {}), ...(plan?.errors ?? {}) }}
          googleUrl={result?.google_url}
          plan={plan}
        />
      ) : (
        !busy && !(form.from.length && !form.to.length) && (
          form.from.length && form.to.length ? (
            <RouteMap
              className="h-80 rounded-2xl lg:h-[480px]"
              fitKey={[...form.from, ...form.to].join()}
              arcs={expandCodes(form.from).flatMap((o) => expandCodes(form.to).map((d) => ({ from: o, to: d })))}
              points={[
                ...expandCodes(form.from).map((c) => ({ code: c, tone: "origin" as const, label: airport(c)?.city ?? c })),
                ...expandCodes(form.to).map((c) => ({ code: c, tone: "dest" as const, label: airport(c)?.city ?? c })),
              ]}
            />
          ) : (
            <Empty title="Where to?">Pick where you&apos;re flying from. Leave To empty to see the cheapest places to go.</Empty>
          )
        )
      )}
      {watch.element}
    </div>
  );
}
