# Performance

Measured 2026-09-25 from San Diego (about 70 ms round trip to Vercel's iad1). Web, engine and the Neon database all run in
us-east-1 / iad1, so no request crosses regions.

## Website

| What | Before | After | How |
|---|---|---|---|
| First load JS on the search page | 518 KB compressed | 253 KB | MapLibre (1 MB raw) loads after the page is interactive, the calendar (react-day-picker + date-fns) on first open (preloaded on hover or focus) |
| Home, first visit: DOM ready / load / LCP | 435 / 550 / 552 ms | 221 / 285 / 228 ms | same |
| Search link, first visit: load / LCP | 303 / 224 ms | 168 / 116 ms | same |
| `/api/v1/fx` | about 120 ms at the function | about 40 ms from the edge | `s-maxage=3600, stale-while-revalidate` |
| `/api/v1/explore/cached` | about 150 ms | edge cached | `s-maxage=600` |
| airports.json (417 KB), airlines.json, map worker | revalidated on every view | cached in the browser for a day | `Cache-Control` in next.config.ts |
| Repeat searches (anyone, 20 min) | | about 0.4 s | shared `search_cache` table |

Server time for a dynamic API call is about 50 ms (the rest is the network round trip).

## Engine

| What | Before | After | How |
|---|---|---|---|
| Google one way, worst case | 6 to 10 s when one Google page was slow | about 2 to 3 s | coverage slices wait at most 2.5 s after the base page, the browser list at most 8 s |
| Google round trip (local, with the real browser Cheapest list) | | about 3 s warm, 8 s cold | the browser list runs in parallel with the page fetches |
| Kiwi, several airport pairs | one pair after another (about 10 s each) | in parallel (4 pairs in 15 s) | thread pool, bounded by Kiwi slots |
| Booking sites (18) | the slowest one held the search (137 s) | at most 45 s, late ones fill the cache | per source deadline |
| Browser jobs on a local runner (Google list, browser airlines, browser booking sites) | one at a time in one tab | up to 4 at once as tabs of the same headless Chrome | worker pool over CDP, one Chrome process |
| Watch check (tracker) | 12 Google searches one after another plus Kiwi | 5 at a time, Kiwi in parallel | thread pool |
| CLI startup (`flightscout --help`) | 0.30 s | 0.15 s | httpx imported only when a request is made |
| Engine import | 0.18 s, 79 MB | same | fine |
| Heavy search (2x2 airports, round trip, Google + Kiwi web + airlines) | | 168 MB peak, 0.65 s CPU | the rest is network wait |
| Engine cold start on Vercel | | no measurable penalty | Fluid compute |

Tried and rejected: blocking images, fonts and CSS in the Google browser page (both Playwright routing and Chrome's
own URL blocking made Google's page about twice as slow).

## Where the time goes now

Almost all remaining time is waiting on the sources themselves: Google pages (0.4 to 1.8 s each, up to 4.8 MB of HTML),
Kiwi's MCP search (about 10 s per call on Kiwi's side), booking sites (10 to 30 s for the metasearch ones). Results
stream in by source group (Google, Kiwi web, airlines, Kiwi, booking sites), so the first flights show in about 2 to 3 s.

## Resource use

- Local runner: one headless Chrome process, shared by all browser jobs, closed after 5 idle minutes and at exit.
  No visible browser windows unless `FLIGHTSCOUT_HEADFUL=1`.
- Local development uses PGlite (embedded), no Docker or VM.
- Vercel engine function: 1024 MB, typical use well under 200 MB per search; kept for concurrent search parts on one
  Fluid instance.
