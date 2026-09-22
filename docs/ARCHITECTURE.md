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
Itinerary { id, source: "google"|"kiwi"|"ryanair"|"serpapi", price, currency, slices: Slice[], booking_url,
            seller?, seller_kind: "airline"|"ota"|"metasearch", self_transfer, baggage?, warnings: string[],
            fetched_at, trip_type: "oneway"|"roundtrip"|"multi" }
Trip      { id, tickets: Itinerary[], total_price, currency, kind: "single"|"split"|"stopover"|"nested"|"multicity",
            stopovers: {airport, hours}[], risks: string[], savings_vs_direct?, score?, route: string[],
            departure, arrival, travel_min }
DatePrice { origin, destination, departure, return_date?, price, currency, source, booking_url? }
Destination { origin, destination, city?, country?, price, currency, departure?, return_date?, source, booking_url?, lat?, lon? }
SearchQuery { origins[], destinations[], departure, return_date?, adults=1, cabin="economy", max_stops?, currency="USD",
              sources=["google","kiwi"], departure_flex_days=0, return_flex_days=0 }
SearchResult { query, trips: Trip[], errors: {source: message}, searched_at, google_url? }
PlanRequest { origins[], destinations[], depart_start, depart_end, return_start?, return_end?, currency,
              max_stopover_days=3, min_connection_hours=3, max_trip_days?, hubs?: string[], max_hubs=10,
              allow_self_transfer=true, include_nested_roundtrips=true, cabin="economy", adults=1 }
PlanResult { trips: Trip[] (sorted by score), direct?: Trip, hubs_tried: string[], requests: number, errors }
```

## Engine HTTP API (FastAPI, header `x-engine-key: $ENGINE_KEY`)

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | /search | SearchQuery | SearchResult |
| POST | /plan | PlanRequest | PlanResult |
| POST | /dates | {origin, destination, start, end, currency, trip_days?} | DatePrice[] |
| POST | /explore | {origin, start, end, currency, nights_min?, nights_max?, sources?} | Destination[] |
| GET | /health | | {ok} |

## Web API `/api/v1` (header `Authorization: Bearer <user api token>`; tracker endpoints use `x-tracker-key`)

| Method | Path | Notes |
|---|---|---|
| GET | /me | user, settings |
| GET/POST | /places, DELETE /places/:id | saved airports: {label, codes[], kind: home\|frequent\|interested} |
| GET/POST | /watches, GET/PATCH/DELETE /watches/:id | watchlist |
| GET | /watches/:id/history | observations for charts |
| POST | /results | {kind: search\|plan\|explore\|dates, query, payload, origin: cli\|mcp\|web} saved to history |
| POST | /watches/:id/observations | [{observed_at, depart_date, return_date?, price, currency, source, kind, route, duration_min, booking_url, trip}] |
| GET | /tracker/watches | (tracker key) every active watch with owner currency |
| POST | /tracker/observations | (tracker key) {watch_id, observations[]} then evaluates alerts |

## Data model (Postgres)

* auth tables (Better Auth: user, session, account, verification, passkey)
* `settings` (user_id pk, currency, default_origins[], planner jsonb, seller_rules jsonb, email_alerts, push_alerts)
* `places` (id, user_id, label, codes text[], kind, color, notes)
* `watches` (id, user_id, name, origins[], destinations[], trip_type, depart_start, depart_end, nights_min, nights_max,
  cabin, adults, max_stops, currency, include_split, alert_below, alert_drop_pct, active, last_checked_at, best_price, best_trip jsonb)
* `observations` (id, watch_id, observed_at, depart_date, return_date, price, currency, price_usd, source, kind,
  route, duration_min, booking_url, trip jsonb nullable)
* `searches` (id, user_id, kind, origin, query jsonb, payload jsonb, created_at)
* `api_tokens` (id, user_id, name, token_hash, prefix, created_at, last_used_at)
* `push_subscriptions` (id, user_id, endpoint, p256dh, auth)
* `alerts` (id, user_id, watch_id, message, price, currency, booking_url, created_at, read_at)

## Seller rules

Every itinerary carries `seller` + `seller_kind`. Users can mark sellers `block` (hidden) or `warn`. Built in warnings:
OTA sold tickets, self transfers (connections not protected), separate tickets in planner trips, airport changes
during a connection, short self transfer buffers, overnight connections.
