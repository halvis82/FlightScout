"use client";
// Streamed flight search shared by the search page and watch pages: each group
// of sources is asked separately, results merge in as they arrive.

import { useEffect, useRef, useState } from "react";
import { api } from "./client";
import { browserGoogleSearch, extensionVersion } from "./extension";
import { localRunnerActive, runnerKnown } from "./local-runner";
import type { PlanResult, SearchQuery, SearchResult } from "./types";

// Fastest first. Google is asked in parts so its flights are on screen as soon
// as its own page is in (about 2 s): the requested dates first, then the full
// Cheapest list (the local runner's Chrome, 3 to 8 s) and the cheapest nearby
// dates (flexible searches). Booking sites in two parts so the quick ones
// don't wait for ITA Matrix and the polling metasearch sites.
export const PARTS: string[][] = [["google_now"], ["google_list"], ["google_flex"], ["kiwiweb"], ["airlines"], ["kiwi"], ["otas_fast"], ["otas_slow"]];
export const PART_LABELS = ["Google Flights", "Google, full list", "Google, nearby dates", "Kiwi.com", "Airlines direct", "Kiwi.com deals", "Booking sites", "More booking sites, ITA Matrix"];
// Kiwi.com sells everything these two parts find: skipped unless Settings
// includes less reliable booking sites (the engine would hide them anyway).
const KIWI_PARTS = new Set(["kiwiweb", "kiwi"]);
export type PartOptions = {
  // flexible dates: ask for the cheapest nearby dates too
  flex?: boolean;
  // a local runner with Chrome: ask for Google's full Cheapest list (the hosted engine gets it embedded)
  list?: boolean;
};
export function partsFor(showUnreliable: boolean, opts: PartOptions = {}) {
  return PARTS.map((sources, i) => ({ sources, label: PART_LABELS[i] })).filter((p) => {
    const s = p.sources[0];
    if (KIWI_PARTS.has(s)) return showUnreliable;
    if (s === "google_flex") return Boolean(opts.flex);
    if (s === "google_list") return Boolean(opts.list);
    return true;
  });
}
export type PartState = { state: "searching" | "done" | "failed"; n: number };
// Parts that take 3 to 60 s: they fill in after the search already reads as done.
export const BACKGROUND_PARTS = new Set(["google_list", "google_flex", "kiwi", "otas_slow"]);

// A later part's answer merged into what's on screen. The same trip from
// two parts keeps the cheaper price (Google's full list can undercut the
// price its page embedded).
export function mergeResults(acc: SearchResult | null, r: SearchResult): SearchResult {
  if (!acc) return r;
  const trips = [...acc.trips];
  const at = new Map(trips.map((t, i) => [t.id, i]));
  for (const t of r.trips) {
    const i = at.get(t.id);
    if (i == null) {
      at.set(t.id, trips.length);
      trips.push(t);
    } else if (t.total_price < trips[i].total_price) trips[i] = t;
  }
  return { ...acc, trips, errors: { ...acc.errors, ...r.errors } };
}

// Google via the visitor's own browser when the FlightScout Helper extension is
// installed (and the local runner isn't running, which already uses their IP).
// Any failure falls back to the server.
export async function searchPart(q: SearchQuery, sources: string[], part: number): Promise<SearchResult> {
  await runnerKnown();
  if (sources[0] === "google_now" && extensionVersion() && !localRunnerActive()) {
    try {
      // the extension does the whole Google search in rounds, list included
      return await browserGoogleSearch<SearchResult>({ ...q, sources: ["google"] }, (body) =>
        api<SearchResult & { need?: string[] }>("/browser", { body: { ...body, part } }),
      );
    } catch {
      /* fall back to the server below */
    }
  }
  return api<SearchResult>("/search", { body: { ...q, sources, part } });
}

export type MulticityLeg = {
  origins: string[];
  destinations: string[];
  date: string;
  before: number;
  after: number;
  arrive_by: string | null;
};

// A search that fills in part by part. `q` null = nothing to search.
export function useLiveSearch(q: SearchQuery | null, legs?: MulticityLeg[] | null, showUnreliable = false) {
  const [result, setResult] = useState<SearchResult | null>(null);
  const [plan, setPlan] = useState<PlanResult | null>(null);
  const [pending, setPending] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const seq = useRef(0);
  const key = JSON.stringify([q, legs, showUnreliable]);
  /* eslint-disable react-hooks/set-state-in-effect -- a new search resets the previous one */
  useEffect(() => {
    const run = ++seq.current; // also drops a search that's still running
    if (!q && !legs?.length) return;
    setError(null);
    if (legs?.length) {
      setPending(1);
      api<PlanResult>("/multicity", { body: { legs, currency: q?.currency, cabin: q?.cabin, adults: q?.adults } })
        .then((r) => run === seq.current && (setPlan(r), setResult(null)))
        .catch((e) => run === seq.current && setError((e as Error).message))
        .finally(() => run === seq.current && setPending(0));
      return;
    }
    let acc: SearchResult | null = null;
    const parts = partsFor(showUnreliable, { flex: Boolean(q!.departure_flex_days || q!.return_flex_days), list: localRunnerActive() });
    let left = parts.length;
    setPending(left);
    setPlan(null);
    parts.forEach(({ sources }, part) =>
      searchPart(q!, sources, part + 1) // part > 0: not saved to history again
        .then((r) => {
          if (run !== seq.current) return;
          acc = mergeResults(acc, r);
          setResult(acc);
        })
        .catch((e) => run === seq.current && part === 0 && setError((e as Error).message))
        .finally(() => run === seq.current && setPending(--left)),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  /* eslint-enable react-hooks/set-state-in-effect */
  return { result, plan, pending, error };
}
