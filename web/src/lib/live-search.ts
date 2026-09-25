"use client";
// Streamed flight search shared by the search page and watch pages: each group
// of sources is asked separately, results merge in as they arrive.

import { useEffect, useRef, useState } from "react";
import { api } from "./client";
import { browserGoogleSearch, extensionVersion } from "./extension";
import { localRunnerActive, runnerKnown } from "./local-runner";
import type { PlanResult, SearchQuery, SearchResult } from "./types";

export const PARTS: string[][] = [["google"], ["kiwiweb"], ["airlines"], ["kiwi"], ["otas"]];

// Google via the visitor's own browser when the FlightScout Helper extension is
// installed (and the local runner isn't running, which already uses their IP).
// Any failure falls back to the server.
export async function searchPart(q: SearchQuery, sources: string[], part: number): Promise<SearchResult> {
  await runnerKnown();
  if (sources[0] === "google" && extensionVersion() && !localRunnerActive()) {
    try {
      return await browserGoogleSearch<SearchResult>({ ...q, sources }, (body) =>
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
export function useLiveSearch(q: SearchQuery | null, legs?: MulticityLeg[] | null) {
  const [result, setResult] = useState<SearchResult | null>(null);
  const [plan, setPlan] = useState<PlanResult | null>(null);
  const [pending, setPending] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const seq = useRef(0);
  const key = JSON.stringify([q, legs]);
  /* eslint-disable react-hooks/set-state-in-effect -- a new search resets the previous one */
  useEffect(() => {
    if (!q && !legs?.length) return;
    const run = ++seq.current;
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
    let left = PARTS.length;
    setPending(left);
    setPlan(null);
    PARTS.forEach((sources, part) =>
      searchPart(q!, sources, part + 1) // part > 0: not saved to history again
        .then((r) => {
          if (run !== seq.current) return;
          if (!acc) acc = r;
          else {
            const seen = new Set(acc.trips.map((t) => t.id));
            acc = { ...acc, trips: [...acc.trips, ...r.trips.filter((t) => !seen.has(t.id))], errors: { ...acc.errors, ...r.errors } };
          }
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
