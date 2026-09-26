# FlightScout

End to end flight finder for people who fly a lot. One search asks Google Flights, ITA Matrix, Kiwi.com, 62 airlines directly and 22 booking sites (Booking.com, Expedia, KAYAK, Priceline, Trip.com, Skiplagged...) at once, builds cheaper routes out of separate tickets (self transfers, stopovers, nested round trips, multi city trips), shows where you can go cheaply, and tracks the routes you care about twice a day so you get price history and alerts. Every result links straight to the page where you can book it, and every source's prices were checked against that site's own booking page.

Website: https://flightscout-app.vercel.app

## Which way should I use it?

Every way has every feature: search, smart routes, multi city, explore, the watchlist with price history and alerts, accounts and login, the airline directory, currencies, the CLI and the MCP server. What changes is whose computer and internet connection do the work.

| | Just the website | **Website + local runner** (recommended) | Everything on your computer | Your own hosted copy |
|---|---|---|---|---|
| Setup | nothing | one command, once | one command, once | one script, once |
| Website | flightscout-app.vercel.app | flightscout-app.vercel.app | http://localhost:3000 | your-name.vercel.app |
| Searches run from | FlightScout's server | **your IP** | **your IP** | your server |
| Sources | Google, ITA Matrix, Kiwi, 27 airlines, 14 booking sites | **all**: + 35 airlines and 8 booking sites that need a browser | all | like "just the website" |
| Search limits | guests 60 an hour, accounts more | **none** (searches skip the server) | **none** | yours to set |
| Account and data | online | online (same as the website) | on this computer, or `--shared` for the online one | your own database |
| Runs in the background | nothing | nothing (starts when the website searches, stops after 10 idle minutes) | nothing (starts when you open localhost:3000, stops a couple of minutes after you close it) | your Vercel |

**Recommendation:** use the website with the local runner. It's the same site and the same account, but faster, with all 62 airlines, no limits, and it keeps the shared server from getting blocked. Run everything on your computer when you want to be independent of the online site entirely.

## Run it on your computer

### Website + local runner (recommended), macOS and Linux

```sh
curl -fsSL https://raw.githubusercontent.com/halvis82/FlightScout/main/scripts/install-runner.sh | sh
```

Then open the website, go to Settings, "Where your searches run", click **Connect to my computer** and allow "local network access" when Chrome asks (once). The header shows **Your IP** when it's in use, and each search shows which source groups are done.

- What it does: installs the `flightscout` command (and uv, a small Python installer, if needed) and registers the runner **on demand**: macOS (launchd) or Linux (systemd) listens on port 8787 and starts the runner when the website searches (1 to 2 s the first time); it exits after 10 quiet minutes. Nothing runs while you're not searching.
- With Google Chrome installed, the browser only airlines and booking sites join in, always headless (no windows).
- Your account, watchlist and history stay the online ones; only the searching moves to your computer.
- Update: run the same command again. Remove: `flightscout serve --uninstall` (or `scripts/uninstall-runner.sh`).
- Windows: `uv tool install 'flightscout[browser] @ git+https://github.com/halvis82/FlightScout#subdirectory=engine'`, then run `flightscout serve` while you search.
- Optional, also check your watches from this computer twice a day: `flightscout login`, then `flightscout serve --install --track`.

### Everything on your computer, macOS and Linux

```sh
curl -fsSL https://raw.githubusercontent.com/halvis82/FlightScout/main/scripts/install-local.sh | sh
```

Then open http://localhost:3000 (bookmark it). That's the whole setup.

- **Only runs while it's open.** Nothing stays running on your computer: the first visit to localhost:3000 starts the website and the engine (a few seconds), and a couple of minutes after you close the last FlightScout tab both stop. The operating system (launchd on macOS, systemd on Linux) just holds the port until you come back.
- **Every feature:** accounts and login (email and password, passkeys), search with every source (plus the browser only airlines and booking sites when Google Chrome is installed, always headless), smart routes, multi city, explore, trip builder, the watchlist with price history and alerts in the page, and no rate limits. Searches use your own IP.
- **Your data stays here:** an embedded database in the install folder, no Docker and no database server. Anyone can make an account on your copy. Your watches are checked when you open FlightScout if the last check is more than 12 hours old, and "Check now" works any time.
- **Or share the online account:** add `--shared` (`... | sh -s -- --shared`) to log in with your usual account and see the same watchlist; the online site keeps checking your watches. It needs the online database's address in `~/.config/flightscout/local.env` as `DATABASE_URL=...`.
- What it installs: the `flightscout` command (with uv, a small Python installer, if needed), Node.js 22 in `~/.config/flightscout/node` only if you don't have it, and the code in `~/.local/share/flightscout/FlightScout`. No admin rights.
- Manage it: `flightscout local status`, `flightscout local update` (latest version), `flightscout local uninstall`. Windows, or without the on demand setup: `flightscout local start` runs it in a terminal and stops the same way.
- Developing FlightScout itself: from a clone, `./scripts/run-local.sh` (or `--shared`) builds and runs your working copy until Ctrl+C.

### Browser extension (Google only)

If you don't want to install anything on your computer: the FlightScout Helper extension (Chrome, Edge, Brave, Arc) makes the Google Flights part of each search run from your browser, so Google prices match what you see on Google yourself. Download it from Settings, then `chrome://extensions`, Developer mode, Load unpacked. See [extension/README.md](extension/README.md).

## Where searches run

| | Server (default) | Extension | Local runner | Everything local |
|---|---|---|---|---|
| Google Flights and its calendar | FlightScout's server | **your browser** | **your computer** | **your computer** |
| ITA Matrix, Kiwi, airlines, booking sites | server | server | **your computer** | **your computer** |
| Browser only airlines and sites | not searched | not searched | **your computer** | **your computer** |

### If the server gets limited

Sites limit how often one address can search, and the server's address is shared by everyone who doesn't run locally. What protects it, and the levers if it isn't enough:

| | |
|---|---|
| Shared cache | The same search by anyone within 20 minutes (calendars 6 h, explore 3 h) is answered from the database without asking any source |
| Rate limits | Per guest IP and per account, per hour (not on local copies) |
| Automatic pause | A source that answers "blocked" (403, 429, captcha) is paused for 10 minutes, doubling up to an hour, instead of being asked again on every search |
| Deadlines | Slow sources never hold a search: booking sites 45 s, ITA Matrix 90 s, and results stream in as each group answers |
| Turn sources off on the server | `FLIGHTSCOUT_DISABLE=otas` (or `kiwi`, `airlines`, `browser`, single names) on the engine's Vercel project; local runners keep everything |
| Paid Google fallback | `SEARCHAPI_KEY` or `SERPAPI_KEY` on the engine: used only when Google blocks the server |
| Move searches off the server | Local runner or extension (above): every visitor who does takes their load with them |

## Features

- **Search**: one way, round trip and multi city, flexible dates per side, nearby airports, presets (weekend, a week, two weeks), prices in the date picker. Results stream in by source group with a clear searching and complete state, and mirror Google Flights' "Best" (its top departing flights, in its order) and "Cheapest" views.
- **Smart routes**: cheaper combinations of separate tickets, stopovers, nested round trips and nearby gateways, with self transfer risks spelled out.
- **Explore**: the cheapest places to go from your airports, on a map, when you leave the destination empty.
- **Watchlist**: watch any search (before or after searching), price history, prices by date, the live flight list, alerts in the page, by push and by email.
- **Sellers**: every result says who sells it (airline, agency, metasearch); block or warn about sellers; bait prices far below the market are flagged; hidden city fares are marked.
- **Airlines tab**: 127 airlines by region with links into their own search, pre-filled with your route.
- Currencies NOK, EUR, USD, GBP, MXN. Guests get everything, saved in the browser; accounts sync and get background tracking.

## Data sources

| Group | What | Where it runs |
|---|---|---|
| Google Flights | every airline Google sells, both its "Best" and "Cheapest" lists, price calendar | server, your browser (extension) or your computer |
| ITA Matrix | Google's fare engine: real prices for any airline | server or your computer |
| Kiwi.com | self transfer combinations, flexible dates, "anywhere" explore | server or your computer |
| Airlines direct (27 over plain HTTP) | Volaris, Frontier, JetBlue, Alaska, Breeze, Aeroméxico, Arajet, Aerolíneas Argentinas, Flair, Sky, Norse, Condor, Widerøe, Volotea, Jet2, Aer Lingus, Vueling, SKY express, Jazeera, FlySafair, Air New Zealand, Biman, FlyArystan, Star Air, Alliance Air, Nok Air, Spring | server or your computer |
| Airlines direct (35 that need a real browser) | United, Southwest, Qatar, Etihad, Air France/KLM, Finnair, TAP, SAS, Norwegian, Transavia, WestJet, Porter, Avianca, Vietnam Airlines, Philippine Airlines, VietJet, SpiceJet, Virgin Australia... | your computer (headless Chrome) |
| Booking sites (14 over HTTP, 8 in a browser) | Skiplagged, Booking.com, Expedia, Orbitz, Travelocity, Priceline, KAYAK, momondo, Cheapflights, Agoda, Wego, Gotogate, Mytrip, EaseMyTrip; Trip.com, Aviasales, eDreams, Opodo, Almosafer, Traveloka, Cleartrip, ixigo | HTTP ones on the server or your computer, browser ones on your computer |
| Fare calendars | Wizz Air, Ryanair, VivaAerobus, Volotea, LEVEL, flydubai, Skyscanner, Kiwi | server or your computer |

The full list with methods and caveats: [docs/SOURCES.md](docs/SOURCES.md) (generated from the code). A few airline sources need the public key their own website sends to every browser; those keys aren't in this repo (env vars in [engine/README.md](engine/README.md)), without them those sources stay off.

## CLI and AI agents

The `flightscout` command (installed by the runner script) does everything the website does and more: `search`, `plan`, `multicity`, `trip`, `explore`, `dates`, `airlines`, `watch`, `places`, `settings`, `history`, with `--format json` or `csv` for scripts and agents. Reference: [docs/CLI.md](docs/CLI.md).

```sh
flightscout search SAN OSL 2026-11-10 --return 2026-11-20
flightscout login --url https://flightscout-app.vercel.app --token fsk_...   # token from Settings, for watches and history
claude mcp add flightscout -- flightscout mcp                                 # flight tools for any Claude session
```

`--sources` takes groups (`google`, `kiwi`, `airlines`, `otas`) or single sources.

## Your own hosted copy

Everything runs on free tiers (Vercel Hobby, Neon, GitHub Actions). Fork the repo, then:

```sh
vercel login && gh auth login
./scripts/setup.sh my-flightscout you@example.com
```

It creates both Vercel projects, a Neon database, all secrets (kept in `~/.config/flightscout/deploy-secrets.env`, Vercel and GitHub only), the tracker's GitHub secrets, and deploys. Only `you@example.com` can sign up; add more emails to `ALLOWED_SIGNUP_EMAILS` on Vercel (`*` allows anyone).

Optional keys: `RESEND_API_KEY` + `ALERT_FROM_EMAIL` for email alerts, GitHub or Google OAuth IDs for social login, `SEARCHAPI_KEY`/`SERPAPI_KEY` for the paid Google fallback.

## How it's built

```
browser ──▶ web/ (Next.js on Vercel: UI, accounts, watchlist, alerts, Postgres on Neon)
   │              │ server side, with ENGINE_KEY
   │              ▼
   │        engine/ (Python on Vercel: sources, planner, explore)
   │
   └──▶ local runner (optional, on demand on your computer: the same engine, your IP, headless Chrome)

GitHub Actions (twice a day) ── engine ──▶ web /api/v1/tracker (price history, alerts)
```

Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/PERFORMANCE.md](docs/PERFORMANCE.md), [engine/README.md](engine/README.md), [web/README.md](web/README.md).

## Tests

| Suite | Command | Runs |
|---|---|---|
| Engine unit tests (offline) | `cd engine && uv run pytest` | every push (GitHub Actions) |
| Engine live source tests | `cd engine && FLIGHTSCOUT_LIVE=1 uv run --extra browser pytest -m live` | nightly (sites that wall off GitHub's servers are skipped there; run from home after changing a source) |
| Web unit tests, types, lint | `cd web && npm test && npx tsc --noEmit && npm run lint` | every push |
| Browser tests (every flow, phone width, no console errors) | `cd web && E2E_BASE_URL=https://flightscout-app.vercel.app npx playwright test` | nightly against the live site |
