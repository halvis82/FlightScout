"use client";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Check, Sparkles, X } from "lucide-react";
import { useApp } from "@/components/app-context";
import { ExplorePanel } from "@/components/explore-panel";
import { RecentRow } from "@/components/recent-row";
import { pushRecent } from "@/lib/recent";
import { ResultsView, mergeTrips } from "@/components/results-view";
import { SearchFormView, defaultForm, formToParams, paramsToForm, type SearchForm } from "@/components/search-form";
import { WatchButton } from "@/components/watch-dialog";
import { Empty, ErrorNote, Spinner } from "@/components/ui";
import { api } from "@/lib/client";
import { extensionVersion } from "@/lib/extension";
import { localRunnerActive } from "@/lib/local-runner";
import { PARTS, PART_LABELS, searchPart, type PartState } from "@/lib/live-search";
import { METROS, airport, expandCodes, loadAirports, nearestAirport } from "@/lib/airports-client";
import { RouteMap } from "@/components/route-map";
import { addDays, dayDiff } from "@/lib/format";
import { cn } from "@/lib/utils";
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
function resetSaved() {
  saved = { form: null, result: null, plan: null };
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}
function persist(next: Saved) {
  saved = next;
  try {
    sessionStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    /* quota or private mode: memory copy is enough */
  }
}

// Where a fresh search starts: the default chosen in Settings, else wherever
// you last searched from, else your first home.
const LAST_FROM = "fs.lastFrom";
// Smart routes fail in technical ways (timeouts, a busy server, a runner
// hiccup): say what it means for the user, not the raw response.
function friendlyPlanError(msg: string) {
  if (/abort|time ?out|took too long|50[234]|failed to fetch|network/i.test(msg)) return "didn't finish in time. The flights above are complete. Search again to retry.";
  if (/^\s*[{<]|\d{3}:/.test(msg) || msg.length > 140) return "something went wrong. The flights above are complete.";
  return msg;
}

function formProblem(from: string[], to: string[]) {
  const same = expandCodes(from).filter((c) => expandCodes(to).includes(c));
  if (same.length) return `${same[0]} is both where you leave from and where you go. Pick a different airport.`;
  // unknown codes (only once the airport list is loaded)
  if (airport("LAX")) {
    const bad = [...from, ...to].find((c) => !METROS[c] && !airport(c));
    if (bad) return `${bad} isn't an airport FlightScout knows. Pick one from the list.`;
  }
  return null;
}

function startOrigin(defaults: string[], places: { kind: string; codes: string[] }[]): string[] {
  if (defaults.length) return defaults;
  try {
    const last = typeof window !== "undefined" ? JSON.parse(localStorage.getItem(LAST_FROM) ?? "null") : null;
    if (Array.isArray(last) && last.length) return last;
  } catch {
    /* ignore */
  }
  const home = places.find((p) => p.kind === "home");
  if (home) return home.codes.slice(0, 1);
  // nothing chosen yet: the airport nearest to where the visitor is (by IP)
  try {
    const geo = typeof window !== "undefined" ? JSON.parse(localStorage.getItem(GEO_FROM) ?? "null") : null;
    if (geo?.code && Date.now() - geo.at < 7 * 86400_000) return [geo.code];
  } catch {
    /* ignore */
  }
  return [];
}

const GEO_FROM = "fs.geoFrom";

// Finds the nearest airport once (cached a week) for visitors with no default,
// no last search and no home, so the first screen shows real suggestions.
function useNearestAirport(needed: boolean, onFound: () => void) {
  useEffect(() => {
    if (!needed) return;
    try {
      const geo = JSON.parse(localStorage.getItem(GEO_FROM) ?? "null");
      if (geo && Date.now() - geo.at < 7 * 86400_000) return;
    } catch {
      /* ignore */
    }
    let gone = false;
    (async () => {
      try {
        const loc = (await (await fetch("/api/v1/geo", { cache: "no-store" })).json()) as { lat?: number; lon?: number };
        if (loc.lat == null || loc.lon == null) return;
        const a = nearestAirport(await loadAirports(), loc.lat, loc.lon);
        if (!a || gone) return;
        localStorage.setItem(GEO_FROM, JSON.stringify({ code: a.iata, at: Date.now() }));
        onFound();
      } catch {
        /* no suggestion then */
      }
    })();
    return () => {
      gone = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [needed]);
}

function SearchPage() {
  const { settings, currency, places } = useApp();
  const router = useRouter();
  const params = useSearchParams();
  const fresh = params.get("new") === "1";
  if (fresh) resetSaved(); // logo click: start over as if the site was just opened
  const hasQuery = Boolean(params.get("from")) || fresh;
  const [edited, setForm] = useState<SearchForm | null>(() => (hasQuery ? null : loadSaved().form));
  // Until the user edits, the form comes from the URL (or their defaults).
  const [, bump] = useState(0);
  const form = edited ?? (settings ? paramsToForm(params, defaultForm(currency, startOrigin(settings.defaultOrigins, places))) : null);
  useNearestAirport(Boolean(settings && !edited && !hasQuery && form && !form.from.length), () => bump((x) => x + 1));
  const [result, setResult] = useState<SearchResult | null>(() => (hasQuery ? null : loadSaved().result));
  const [plan, setPlan] = useState<PlanResult | null>(() => (hasQuery ? null : loadSaved().plan));
  useEffect(() => {
    if (edited || result || plan) persist({ form: edited, result, plan });
  }, [edited, result, plan]);
  const [busy, setBusy] = useState(false);
  const [planBusy, setPlanBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const runSeq = useRef(0);
  const [stale, setStale] = useState(false);
  const [, setPending] = useState(0);
  const [parts, setParts] = useState<PartState[]>([]);
  const [finished, setFinished] = useState<{ secs: number; failed: number } | null>(null);
  const lastRun = useRef<string | null>(null);
  // Each new search is a browser history entry, so Back and Forward move
  // between searches: the address this page last wrote, to tell those apart.
  const paramStr = params.toString();
  const ownUrl = useRef(paramStr);
  const searched = useRef(false);
  const go = useCallback(
    (qs: string) => {
      // the first search of a page view replaces (a shared link gets tidied, not doubled)
      const first = !searched.current;
      searched.current = true;
      if (qs === ownUrl.current) return;
      const push = !first && Boolean(new URLSearchParams(ownUrl.current).get("from"));
      ownUrl.current = qs;
      (push ? router.push : router.replace)(qs ? `/?${qs}` : "/", { scroll: false });
    },
    [router],
  );
  useEffect(() => {
    if (paramStr === ownUrl.current) return;
    ownUrl.current = paramStr;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (params.get("from")) setForm(null); // Back or Forward to another search: the form follows the address and searches again
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paramStr]);

  const run = useCallback(
    async (f0: SearchForm) => {
      setForm(f0);
      try {
        localStorage.setItem(LAST_FROM, JSON.stringify(f0.from));
      } catch {
        /* ignore */
      }
      if (f0.tripType !== "multicity" && f0.to.length)
        pushRecent({ from: f0.from, to: f0.to, tripType: f0.tripType, depart: f0.depart, ret: f0.ret });
      const f = { ...f0, currency };
      lastRun.current = JSON.stringify([f0.from, f0.to, f0.depart, f0.ret, f0.tripType, f0.flex, f0.retFlex, f0.cabin, f0.adults, f0.stops, f0.nearby]);
      setErr(null);
      setStale(true); // keep showing the previous results, dimmed
      setPending(PARTS.length);
      setPlan(null);
      setBusy(true);
      setFinished(null);
      setElapsed(0);
      const t0 = Date.now();
      const timer = setInterval(() => setElapsed(Math.round((Date.now() - t0) / 1000)), 1000);
      go(formToParams(f).toString());
      if (f.tripType === "multicity") {
        // flights must be in date order; say which one isn't instead of searching
        const bad = f.legs.findIndex((l, i) => i > 0 && l.flex !== "by" && l.date < f.legs[i - 1].date);
        if (bad > 0) {
          clearInterval(timer);
          setBusy(false);
          setStale(false);
          setErr(`Flight ${bad + 1} leaves before flight ${bad}. Check the dates.`);
          return;
        }
        const legs = f.legs.map((l, i) => {
          const prevDate = i > 0 ? f.legs[i - 1].date : null;
          const by = l.flex === "by";
          const n = by ? 0 : Number(l.flex);
          return {
            origins: expandCodes(i === 0 ? f.from : f.legs[i - 1].to),
            destinations: expandCodes(l.to),
            date: l.date,
            // "arrive by": any day from the previous flight up to this date
            before: by ? (prevDate ? Math.max(0, dayDiff(prevDate, l.date)) : 14) : n,
            after: by ? 0 : n,
            arrive_by: by ? l.date : null,
          };
        });
        const runId = ++runSeq.current;
        setPlanBusy(false); // a still running smart route search belongs to the old form
        // never hang silently: give up with a message after 4 minutes
        const ctl = new AbortController();
        const limit = setTimeout(() => ctl.abort(), 240_000);
        await api<PlanResult>("/multicity", {
          body: { legs, currency: f.currency, cabin: f.cabin, adults: f.adults },
          signal: ctl.signal,
        })
          .then((r) => {
            if (runSeq.current !== runId) return;
            setResult(null); // never show a previous one way / round trip search under a multi city heading
            setPlan(r);
            setFinished({ secs: Math.round((Date.now() - t0) / 1000), failed: 0 });
          })
          .catch((e) => {
            if (runSeq.current !== runId) return;
            setErr(ctl.signal.aborted ? "The multi city search took too long. Try again, or with fewer flexible days." : (e as Error).message);
          })
          .finally(() => {
            clearTimeout(limit);
            if (runSeq.current !== runId) return;
            setStale(false);
            setBusy(false);
          });
        clearInterval(timer);
        return;
      }
      // say what's wrong instead of searching something that can't exist
      const problem = formProblem(f.from, f.to);
      if (problem) {
        clearInterval(timer);
        setBusy(false);
        setStale(false);
        setParts([]);
        setErr(problem);
        return;
      }
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
      // Stream: ask each group of sources separately and show results as each
      // arrives. Earlier results stay on screen (dimmed) until the first part
      // of the new search lands.
      const runId = ++runSeq.current;
      let acc: SearchResult | null = null;
      let searchId: number | null = null; // history row, saved with the first part
      let pending = PARTS.length;
      const states: PartState[] = PARTS.map(() => ({ state: "searching", n: 0 }));
      setParts([...states]);
      setFinished(null);
      const searchP = Promise.all(
        PARTS.map((sources, part) =>
          searchPart(q, sources, part)
            .then((r) => {
              if (runSeq.current !== runId) return;
              states[part] = { state: "done", n: r.trips.length };
              if (part === 0) searchId = (r as { search_id?: number | null }).search_id ?? null;
              if (!acc) acc = r;
              else {
                const seen = new Set(acc.trips.map((t) => t.id));
                acc = { ...acc, trips: [...acc.trips, ...r.trips.filter((t) => !seen.has(t.id))], errors: { ...acc.errors, ...r.errors } };
              }
            })
            .catch((e) => {
              states[part] = { state: "failed", n: 0 };
              if (runSeq.current === runId && part === 0) setErr((e as Error).message);
            })
            .finally(() => {
              pending -= 1;
              if (runSeq.current !== runId) return;
              setPending(pending);
              setParts([...states]);
              // swap in new results once some flights arrived (or all parts are done)
              if (acc && (acc.trips.length || pending === 0)) {
                setResult(acc);
                setStale(false);
              }
              if (pending === 0) {
                if (!acc) setResult(null);
                setStale(false);
                setBusy(false);
                setFinished({ secs: Math.round((Date.now() - t0) / 1000), failed: states.filter((x) => x.state === "failed").length });
                // history keeps the whole result, not just the first part
                if (searchId != null && acc) {
                  const all = acc as SearchResult;
                  api(`/searches/${searchId}`, { method: "PATCH", body: { payload: { ...all, search_id: undefined } } }).catch(() => {});
                }
              }
            }),
        ),
      );
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
            // automatic on every search, so keep it light on the shared server
            // (your own computer and watches use the full settings)
            max_hubs: localRunnerActive() ? p.max_hubs : Math.min(p.max_hubs ?? 6, 6),
            max_stopover_days: localRunnerActive() ? p.max_stopover_days : Math.min(p.max_stopover_days ?? 2, 2),
          },
        })
          // a newer search (or a switch to multi city) owns the results now
          .then((r) => {
            if (runSeq.current === runId) setPlan(r);
          })
          .catch((e) => {
            // smart routes are a bonus: never let their limit or failure look like an error
            const msg = (e as Error).message;
            if (runSeq.current === runId && !/limit|429|too many/i.test(msg))
              setErr((x) => (x ? x + " · " : "") + `Smart routes: ${friendlyPlanError(msg)}`);
          })
          .finally(() => {
            if (runSeq.current === runId) setPlanBusy(false);
          });
      }
      await Promise.all([searchP, planP]);
      clearInterval(timer);
    },
    [go, settings, currency],
  );
  useEffect(() => {
    if (!fresh) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setForm(null);
    setResult(null);
    setPlan(null);
    setErr(null);
    lastRun.current = null;
    ownUrl.current = "";
    router.replace("/", { scroll: false });
  }, [fresh, router]);

  // Search by itself as soon as the form is complete (from, to, dates) and
  // whenever it changes: picking a destination, arrows, presets, flexibility.
  const formKey = form
    ? JSON.stringify([form.from, form.to, form.depart, form.ret, form.tripType, form.flex, form.retFlex, form.cabin, form.adults, form.stops, form.nearby])
    : "";
  useEffect(() => {
    if (!form || form.tripType === "multicity" || !form.to.length || !form.from.length) return;
    if (lastRun.current === null && result) {
      lastRun.current = formKey; // restored from a tab switch: don't re-run
      return;
    }
    if (formKey === lastRun.current) return;
    const t = setTimeout(() => run(form), 600);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [formKey]);

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
      <SearchFormView
        value={form}
        onChange={(next) => {
          // switching to or from multi city: old results don't belong to the new form
          if (next.tripType !== form.tripType && (next.tripType === "multicity" || form.tripType === "multicity")) {
            setResult(null);
            setPlan(null);
            setErr(null);
            lastRun.current = null;
          }
          // clearing the destination goes back to exploring
          if (!next.to.length && form.to.length && next.tripType !== "multicity") {
            setResult(null);
            setPlan(null);
            lastRun.current = null;
          }
          setForm(next);
        }}
        onSubmit={() => {
          if (form.tripType !== "multicity" && !form.to.length) {
            setResult(null);
            setPlan(null);
            lastRun.current = null;
            go(formToParams(form).toString());
            return;
          }
          run(form);
        }}
        busy={busy}
      />
      <RecentRow
        onPick={(r) => {
          const next: SearchForm = { ...form, from: r.from, to: r.to, tripType: r.tripType, depart: r.depart, ret: r.ret };
          setForm(next);
        }}
      />
      {form.tripType !== "multicity" && parts.length > 0 && (busy || finished) && (
        <div className="space-y-1.5">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
            {busy ? (
              <span className="inline-flex items-center gap-2 text-muted">
                <Spinner /> Searching, results appear as each source answers
                <span className="tabular-nums text-faint">{elapsed}s</span>
              </span>
            ) : (
              finished && (
                <span className="inline-flex items-center gap-1.5 font-medium text-good">
                  <Check className="size-4" /> Search complete: {result?.trips.length ?? 0} flights in {finished.secs}s
                  {finished.failed > 0 && <span className="font-normal text-faint">({finished.failed} source group{finished.failed > 1 ? "s" : ""} didn&apos;t answer)</span>}
                </span>
              )
            )}
            {busy && !extensionVersion() && !localRunnerActive() && elapsed >= 4 && (
              <a href="/settings#own-ip" className="text-xs text-faint underline-offset-2 hover:text-fg hover:underline">
                Faster: search from your own IP
              </a>
            )}
          </div>
          <div className="flex flex-wrap gap-1.5" aria-label="Sources">
            {parts.map((p, i) => (
              <span
                key={i}
                className={cn(
                  "inline-flex h-6 items-center gap-1 rounded-full border px-2 text-xs",
                  p.state === "searching" && "border-border text-muted",
                  p.state === "done" && "border-good/30 bg-good-soft/40 text-good",
                  p.state === "failed" && "border-border text-faint line-through",
                )}
                title={p.state === "failed" ? "Didn't answer this time" : undefined}
              >
                {p.state === "searching" ? <Spinner className="size-3" /> : p.state === "done" ? <Check className="size-3" /> : <X className="size-3" />}
                {PART_LABELS[i]}
                {p.state === "done" && <span className="tabular-nums opacity-70">{p.n}</span>}
              </span>
            ))}
          </div>
        </div>
      )}
      {form.tripType === "multicity" && busy && (
        <div className="flex items-center gap-2 text-sm text-muted">
          <Spinner /> Searching every flight of the trip <span className="tabular-nums text-faint">{elapsed}s</span>
        </div>
      )}
      {form.tripType === "multicity" && !busy && finished && plan && (
        <div className="inline-flex items-center gap-1.5 text-sm font-medium text-good">
          <Check className="size-4" /> Search complete: {plan.trips.length} trips in {finished.secs}s
        </div>
      )}
      {planBusy && (
        <div className="flex items-center gap-2 text-sm text-muted">
          <Sparkles className="size-3.5 text-info" /> Also looking for cheaper combinations (separate tickets, nearby gateways, stopovers). About a minute.
        </div>
      )}
      {err && <ErrorNote>{err}</ErrorNote>}
      {/* Watch works before searching too: as soon as the form is complete */}
      {(hasResults ||
        (form.from.length > 0 &&
          (form.tripType === "multicity"
            ? form.legs.length > 0 && form.legs.every((l, i) => l.to.length && (i === 0 || l.date >= form.legs[i - 1].date))
            : form.to.length > 0))) && (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="text-sm text-muted">
            {form.tripType === "multicity"
              ? [form.from.join("/"), ...form.legs.map((l) => l.to.join("/"))].join(" → ")
              : `${form.from.join("/")} to ${form.to.join("/")} · ${form.tripType === "roundtrip" ? `${dayDiff(form.depart, form.ret)} nights` : "one way"}`}
          </div>
          <WatchButton
            seed={trips}
            watch={
              form.tripType === "multicity"
                ? {
                    name: [form.from.join("/"), ...form.legs.map((l) => l.to.join("/"))].join(" → "),
                    origins: form.from,
                    destinations: form.legs.at(-1)?.to ?? [],
                    trip_type: "multicity",
                    depart_start: form.legs[0]?.date ?? form.depart,
                    depart_end: form.legs.at(-1)?.date ?? form.depart,
                    nights_min: null,
                    nights_max: null,
                    legs: form.legs.map((l, i) => {
                      const by = l.flex === "by";
                      const prev = i > 0 ? form.legs[i - 1].date : null;
                      return {
                        origins: i === 0 ? form.from : form.legs[i - 1].to,
                        destinations: l.to,
                        date: l.date,
                        before: by ? (prev ? Math.max(0, dayDiff(prev, l.date)) : 14) : Number(l.flex),
                        after: by ? 0 : Number(l.flex),
                        arrive_by: by ? l.date : null,
                      };
                    }),
                    currency: form.currency,
                    cabin: form.cabin,
                    adults: form.adults,
                  }
                : {
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
                    max_stops: form.stops === "any" ? null : Number(form.stops),
                    include_split: form.smart,
                  }
            }
          />
        </div>
      )}
      {form.tripType !== "multicity" && !form.to.length && form.from.length > 0 && !hasResults && (
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
        <div className={stale && busy ? "pointer-events-none opacity-50 transition-opacity" : "transition-opacity"}>
        <ResultsView
          trips={trips}
          query={result?.query ?? { origins: form.from, destinations: form.to }}
          errors={{ ...(result?.errors ?? {}), ...(plan?.errors ?? {}) }}
          googleUrl={result?.google_url}
          plan={plan}
        />
        </div>
      ) : (
        !busy && !(form.from.length && !form.to.length) && (
          form.tripType === "multicity" && form.from.length && form.legs.some((l) => l.to.length) ? (
            <RouteMap
              className="h-80 rounded-2xl lg:h-[480px]"
              fitKey={JSON.stringify(form.legs.map((l) => l.to)) + form.from.join()}
              arcs={form.legs
                .map((l, i) => ({ from: expandCodes(i ? form.legs[i - 1].to : form.from)[0], to: expandCodes(l.to)[0] }))
                .filter((a) => a.from && a.to)}
              points={[form.from, ...form.legs.map((l) => l.to)]
                .map((c) => expandCodes(c)[0])
                .filter(Boolean)
                .map((c, i) => ({ code: c, tone: i === 0 ? ("origin" as const) : ("dest" as const), label: airport(c)?.city ?? c }))}
            />
          ) : form.tripType !== "multicity" && form.from.length && form.to.length ? (
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
    </div>
  );
}
