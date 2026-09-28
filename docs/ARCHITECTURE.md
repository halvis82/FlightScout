# FlightScout architecture

```
                ┌──────────────────────────── Vercel ─────────────────────────────┐
 browser ──────▶│ web/  Next.js (UI + /api/v1 REST + auth + Postgres via Drizzle) │
                │        │ server side fetch with ENGINE_KEY                      │
                │        ▼                                                         │
                │ engine/ FastAPI (Python, stateless search + planner)            │
                └──────────────────────────────────────────────────────────────────┘
 CLI / MCP (local, residential IP) ── runs engine in process ── pushes results ──▶ web /api/v1 (user token)
 GitHub Actions cron (tracker)     ── runs engine in process ── pushes observations ▶ web /api/v1/tracker (TRACKER_KEY)
```

* `engine/` Python package `flightscout`. Sources (Google via fli, Kiwi MCP, Ryanair, SerpApi optional),
  normalization, split ticket / stopover planner, explore, CLI (`flightscout`), MCP server, tracker, FastAPI app.
* `web/` Next.js App Router, TypeScript, Tailwind, Better Auth, Drizzle ORM on Postgres (Neon), MapLibre
  (OpenFreeMap tiles), Recharts. Owns all user data.
* Price history lives in Postgres `observations`. Everything the CLI, MCP or tracker finds is pushed to the web API
  so it shows up in the browser.

## Shared JSON shapes (engine `models.py` is the source of truth)

```ts
Segment   { origin, destination, departure, arrival /* local ISO, no tz */, carrier, carrier_name?, flight_number?, duration_min?, aircraft? }
Slice     { segments: Segment[], duration_min, origin, destination, departure, arrival, stops, carriers: string[] }
Itinerary { id, source: one of the ~100 sources (docs/SOURCES.md), price (all passengers), currency, slices: Slice[], booking_url,
            seller?, seller_kind: "airline"|"ota"|"metasearch", self_transfer, baggage?, warnings: string[],
            fetched_at, trip_type: "oneway"|"roundtrip"|"multi" }
Trip      { id, tickets: Itinerary[], total_price, currency, kind: "single"|"split"|"stopover"|"nested"|"multicity"|"nearby",
            stopovers: {airport, hours}[], risks: string[], note? ("Lands at TRF (Sandefjord, Torp), 122 km from OSL"),
            savings_vs_direct?, score?, route: string[],
            departure, arrival, travel_min }
DatePrice { origin, destination, departure, return_date?, price, currency, source, booking_url? }
Destination { origin, destination, city?, country?, price, currency, departure?, return_date?, source, booking_url?, lat?, lon? }
SearchQuery { origins[] (<=12), destinations[] (<=12), departure, return_date?, adults=1..9, cabin="economy", max_stops? (0..3),
              currency="USD", sources=["google","kiwi"] (or groups: airlines, otas, otas_fast, otas_slow),
              departure_flex_days=0..10, return_flex_days=0..10, nearby_km=0..300 }
SearchResult { query, trips: Trip[], errors: {source: message}, searched_at, google_url? }
PlanRequest { origins[], destinations[], depart_start, depart_end, return_start?, return_end?, currency,
              max_stopover_days=3, min_connection_hours=3, max_trip_days?, hubs?: string[], max_hubs=10,
              allow_self_transfer=true, include_nested_roundtrips=true, cabin="economy", adults=1,
              discover_hubs=true, nearby_km=200, reprice_with_airlines=true,
              known_from_origin: {code: usd}, known_to_dest: {code: usd} }   # fare hints from the website
PlanResult { trips: Trip[] (sorted by score), direct?: Trip, hubs_tried: string[], requests: number, errors }
```

## Smart routes (engine/src/flightscout/planner.py)

1. Direct tickets on Google and Kiwi. A "city" answer at another airport becomes kind `nearby` with a note.
2. Layovers: gateways near either end, hubs on the way (static list, detour limit), and layovers real fares
   found (`discover_hubs`: Kiwi's cheapest flight to every city from each end, the engine's fare memory
   (`farememory.py`, SQLite next to the cache) and the website's shared fare memory passed as hints).
3. Legs priced on Google per hub and on Kiwi a whole row of layovers per request (`kiwiweb.search_window`).
   Legs that fly more than twice their own distance are dropped.
4. Round trips: split outbound x split return, and nested round trips through the most promising hubs.
5. Nearby airports at either end (within `nearby_km`), kept only when 10% cheaper than the best normal ticket.
6. The best split and stopover trips re-priced on the airlines' own sites (`airlines` source group), swapping
   in a cheaper leg wherever the connection still works.

Multi city (`multicity.py`) and the trip builder price each leg on Kiwi (both APIs), Google and, for multi
city, the airlines' own sites.

## Engine HTTP API (FastAPI, header `x-engine-key: $ENGINE_KEY`)

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | /search | SearchQuery | SearchResult |
| POST | /plan | PlanRequest | PlanResult |
| POST | /dates | {origin, destination, start, end, currency, trip_days?} | DatePrice[] |
| POST | /explore | {origin, start, end, currency, nights_min?, nights_max?, sources?, regions?, batch?} | {destinations, errors} |
| POST | /trip | TripRequest | PlanResult |
| POST | /multicity | MultiRequest | PlanResult |
| POST | /google/browser | SearchQuery + pages (extension mode) | {need: urls} or SearchResult |
| GET | /health | | {ok, local, version, api} (api level: the website skips older local runners) |
| GET | /alive | | {ok} (counts as activity for an on demand runner) |

Bad input answers 422 with a readable message. Outside local mode the engine refuses to run without ENGINE_KEY.
In local mode (`flightscout serve`) only requests addressed to 127.0.0.1/localhost are served (DNS rebinding) and
CORS allows the configured website origins.

## Web API `/api/v1` (header `Authorization: Bearer <user api token>`; tracker endpoints use `x-tracker-key`)

| Method | Path | Notes |
|---|---|---|
| GET | /me | user, settings |
| GET/POST | /places, DELETE /places/:id | saved airports: {label, codes[], kind: home\|frequent\|interested} |
| GET/POST | /watches, GET/PATCH/DELETE /watches/:id | watchlist |
| GET | /watches/:id/history | observations for charts |
| POST | /results | {kind: search\|plan\|explore\|dates\|trip\|multicity, query, payload, origin: cli\|mcp\|web\|local} saved to history (a repeat within 30 min replaces its row) |
| PATCH | /searches/:id | {payload}: the whole streamed result once every part is in |
| GET | /fares?origin&destination&from&to | cheapest known one way USD prices from the origin and to the destination (smart route hints) |
| POST | /watches/:id/check | price a watch now (rate limited) |
| POST | /watches/:id/observations | [{observed_at, depart_date, return_date?, price, currency, source, kind, route, duration_min, booking_url, trip}] |
| GET | /tracker/watches | (tracker key) every active watch with owner currency |
| POST | /tracker/observations | (tracker key) {watch_id, observations[]} then evaluates alerts |

## Data model (Postgres)

* auth tables (Better Auth: user, session, account, verification, passkey)
* `settings` (user_id pk, currency, default_origins[], planner jsonb, seller_rules jsonb, email_alerts, push_alerts)
* `places` (id, user_id, label, codes text[], kind, color, notes)
* `watches` (id, user_id, name, origins[], destinations[], trip_type, legs jsonb, signature, depart_start, depart_end,
  nights_min, nights_max, cabin, adults, max_stops, currency, include_split, alert_below, alert_drop_pct, active,
  last_checked_at, best_price, prev_price, lowest_price, best_trip jsonb, prices_since)
  best_price is the cheapest fresh observation (last 24 h, since prices_since); an edit that changes the search resets it.
* `observations` (id, watch_id, observed_at, depart_date, return_date, price, currency, price_usd, source, kind,
  route, duration_min, booking_url, trip jsonb nullable)
* `searches` (id, user_id, kind, origin, query jsonb, payload jsonb, created_at)
* `api_tokens` (id, user_id, name, token_hash, prefix, parent_id (revoked with its parent), created_at, last_used_at)
* `fare_memory` (origin, dest, day, usd, seen_at): cheapest one way price per route and day from every result, 14 days
* `search_cache` (key, kind, payload, created_at): the same search by anyone within minutes is answered from here
* `rate_limits`, `auth_rate_limit`, `explore_cache`
* `push_subscriptions` (id, user_id, endpoint, p256dh, auth)
* `alerts` (id, user_id, watch_id, message, price, currency, booking_url, created_at, read_at)

## Seller rules

Every itinerary carries `seller` + `seller_kind`. Only reliable sellers show by default (`sellers.RELIABLE`: airlines, Google Flights and ITA Matrix, and the major booking sites of Expedia Group and Booking Holdings). Every other seller (Kiwi.com, Mytrip, Gotogate, eDreams, Opodo, Trip.com, EaseMyTrip, Skiplagged, CheapOair, small agencies passed through by metasearch sites...) is hidden unless the rules include `"*unreliable": "warn"`, which the Settings checkbox "Include less reliable booking sites" (off by default) sets; they then carry a "Less reliable seller" warning. While hidden, sources that only sell through such sellers (`sellers.UNRELIABLE_SOURCES`) aren't asked at all, the smart route planner still uses Kiwi to find legs but swaps them for the airline's own fare, and the tracker skips Kiwi prices. Users can mark sellers `block` (hidden) or `warn`. Built in warnings:
OTA sold tickets, self transfers (connections not protected), separate tickets in planner trips, airport changes
during a connection, short self transfer buffers, overnight connections.
