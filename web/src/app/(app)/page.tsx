"use client";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Eye, Sparkles } from "lucide-react";
import { useApp } from "@/components/app-context";
import { ResultsView, mergeTrips } from "@/components/results-view";
import { SearchFormView, defaultForm, formToParams, paramsToForm, type SearchForm } from "@/components/search-form";
import { useWatchDialog } from "@/components/watch-dialog";
import { Button, Empty, ErrorNote, Spinner } from "@/components/ui";
import { api } from "@/lib/client";
import { expandCodes } from "@/lib/airports-client";
import { addDays, dayDiff } from "@/lib/format";
import type { PlanResult, SearchQuery, SearchResult } from "@/lib/types";

export default function Page() {
  return (
    <Suspense>
      <SearchPage />
    </Suspense>
  );
}

function SearchPage() {
  const { settings, currency } = useApp();
  const router = useRouter();
  const params = useSearchParams();
  const [edited, setForm] = useState<SearchForm | null>(null);
  // Until the user edits, the form comes from the URL (or their defaults).
  const form = edited ?? (settings ? paramsToForm(params, defaultForm(currency, settings.defaultOrigins)) : null);
  const [result, setResult] = useState<SearchResult | null>(null);
  const [plan, setPlan] = useState<PlanResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [planBusy, setPlanBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const autoRan = useRef(false);
  const watch = useWatchDialog();

  const run = useCallback(
    async (f: SearchForm) => {
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
        return_flex_days: f.tripType === "roundtrip" ? f.flex : 0,
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
            return_start: q.return_date ? addDays(f.ret, -f.flex) : null,
            return_end: q.return_date ? addDays(f.ret, f.flex) : null,
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
    [router, settings],
  );

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
                nights_min: form.tripType === "roundtrip" ? Math.max(0, dayDiff(form.depart, form.ret) - form.flex) : null,
                nights_max: form.tripType === "roundtrip" ? dayDiff(form.depart, form.ret) + form.flex : null,
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
      {hasResults ? (
        <ResultsView
          trips={trips}
          query={result?.query ?? { origins: form.from, destinations: form.to }}
          errors={{ ...(result?.errors ?? {}), ...(plan?.errors ?? {}) }}
          googleUrl={result?.google_url}
          plan={plan}
        />
      ) : (
        !busy && (
          <Empty title="Search every source at once">
            Pick where you&apos;re flying from and to. FlightScout checks Google Flights and Kiwi.com together, and with smart routes on it
            also builds cheaper combinations of separate tickets through hub airports.
          </Empty>
        )
      )}
      {watch.element}
    </div>
  );
}
