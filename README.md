# FlightScout

End to end flight finder for people who fly a lot. One search asks Google Flights, ITA Matrix, Kiwi.com, 62 airlines directly and 22 booking sites (Booking.com, Expedia, KAYAK, Priceline, Trip.com, Skiplagged...) at once, builds cheaper routes out of separate tickets (self transfers, stopovers, nested round trips, multi city trips), shows where you can go cheaply, and tracks the routes you care about twice a day so you get price history and alerts. Every result links straight to the page where you can book it, and every source's prices were checked against that site's own booking page.

Three ways to use it, all sharing one account and database:

| | |
|---|---|
| **Website** | https://flightscout-app.vercel.app. Works as a guest (data kept in your browser) or signed in (sync, background tracking, alerts) |
| **CLI** | Everything the website does and more ([docs/CLI.md](docs/CLI.md)): `search`, `plan`, `multicity`, `explore`, `dates`, `airlines`, `watch`, `settings`... with `--format json/csv` for scripts and agents |
| **MCP server** | `claude mcp add flightscout -- flightscout mcp` gives any Claude session flight tools. Results show up on the site |

## How it works

```
browser ──▶ web/ (Next.js on Vercel: UI, accounts, watchlist, alerts, Postgres)
   │              │ server side, with ENGINE_KEY
   │              ▼
   │        engine/ (Python on Vercel: sources, planner, explore)
   │
   └──▶ local runner (optional, on demand on your computer: same engine, your home IP, headless Chrome)

GitHub Actions (twice a day) ── engine + headless browser ──▶ web /api/v1/tracker (price history, alerts)
```

Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [engine/README.md](engine/README.md), [web/README.md](web/README.md).

## Data sources

| Group | What | Where it runs |
|---|---|---|
| Google Flights | every airline Google sells, both its "Best" and "Cheapest" lists, price calendar | server, your browser (extension) or your computer |
| Kiwi.com | self transfer combinations, flexible dates, "anywhere" explore | server or your computer |
| Airlines direct (27 over plain HTTP) | Volaris, Frontier, JetBlue, Alaska, Breeze, Aeroméxico, Arajet, Aerolíneas Argentinas, Flair, Sky, Norse, Condor, Widerøe, Volotea, Jet2, Aer Lingus, Vueling, SKY express, Jazeera, FlySafair, Air New Zealand, Biman, FlyArystan, Star Air, Alliance Air, Nok Air, Spring | server or your computer |
| Airlines direct (35 that need a real browser) | United, Southwest, Qatar, Etihad, Air France/KLM, Finnair, TAP, SAS, Norwegian, Transavia, WestJet, Porter, Avianca, Vietnam Airlines, Philippine Airlines, VietJet, SpiceJet, Virgin Australia... | your computer only (headless Chrome) |
| Booking sites and fare engines (15 over HTTP, 8 in a browser) | ITA Matrix, Skiplagged (incl. hidden city, clearly marked), Booking.com, Expedia, Orbitz, Travelocity, Priceline, KAYAK, momondo, Cheapflights, Agoda, Wego, Gotogate, Mytrip, EaseMyTrip; Trip.com, Aviasales, eDreams, Opodo, Almosafer, Traveloka, Cleartrip, ixigo | HTTP ones on the server or your computer, browser ones on your computer |
| Fare calendars | Wizz Air, Ryanair, VivaAerobus, Volotea, LEVEL, flydubai, Skyscanner | server or your computer |

The full list with methods and caveats: [docs/SOURCES.md](docs/SOURCES.md). Some airline sources need the public key their own website sends to every browser; those keys aren't in this repo (set the env vars in [engine/README.md](engine/README.md)), without them those sources stay off. Booking site prices far below what Google, Kiwi or the airline ask for the same flights are flagged, since they tend to grow at checkout.

## Where searches run

The website works the same in every mode; only whose internet connection talks to the airlines changes. Settings, "Where your searches run", shows which mode is active.

| | Server (default) | Extension | Local runner | Everything local |
|---|---|---|---|---|
| Google Flights and its calendar | FlightScout's server | **your browser** | **your computer** | **your computer** |
| Kiwi, airlines, booking sites | server | server | **your computer** | **your computer** |
| Browser only airlines and sites | not searched | not searched | **your computer** | **your computer** |
| Website | flightscout-app.vercel.app | same | same | **localhost:3000** |
| Install | nothing | [extension/](extension/README.md) (Chrome, Edge, Brave, Arc) | one command (below) | clone and `./scripts/run-local.sh` |

**Local runner (recommended), macOS and Linux:**

```sh
curl -fsSL https://raw.githubusercontent.com/halvis82/FlightScout/main/scripts/install-runner.sh | sh
```

It installs the `flightscout` command and registers it on demand: the system (launchd on macOS, a systemd socket on Linux) holds port 8787, starts the runner when the website sends a search (1 to 2 s the first time) and the runner exits after 10 quiet minutes. Nothing runs while you're not searching. The website finds it by itself; the header then shows "Your IP". Remove it with `flightscout serve --uninstall` (or `scripts/uninstall-runner.sh`). On Windows, run `flightscout serve` while you search. With Google Chrome installed, the browser only airlines and booking sites are added, always headless (no windows).

**Everything on your computer** (no Vercel, no database server, guest mode or local accounts): `./scripts/run-local.sh` from a clone. It uses the runner, an embedded database (PGlite) and serves the site on http://localhost:3000 until you press Ctrl+C.

**Your own hosted copy** on your own free accounts: see "Self host your own copy" below.

### If the server gets limited

Sites limit how often one address can search, and the server's address is shared by everyone who doesn't run locally. What protects it, and the levers if it isn't enough:

| | |
|---|---|
| Shared cache | The same search by anyone within 20 minutes (calendars 6 h, explore 3 h) is answered from the database without asking any source |
| Rate limits | Per guest IP and per account, per hour |
| Automatic pause | A source that answers "blocked" (403, 429, captcha) is paused for 10 minutes, doubling up to an hour, instead of being asked again on every search |
| Deadlines | Slow booking sites and browser sources never hold a search more than 45 s |
| Turn sources off on the server | `FLIGHTSCOUT_DISABLE=otas` (or `kiwi`, `airlines`, single names) on the engine's Vercel project; the local runner keeps everything |
| Paid Google fallback | `SEARCHAPI_KEY` or `SERPAPI_KEY` on the engine: used only when Google blocks the server |
| Move searches off the server | Extension or local runner (above); every visitor who does takes their load with them |

## Tests

| Suite | Command | Runs |
|---|---|---|
| Engine unit tests (offline) | `cd engine && uv run pytest` | every push (GitHub Actions) |
| Engine live source tests | `cd engine && FLIGHTSCOUT_LIVE=1 uv run pytest -m live` | nightly |
| Web unit tests | `cd web && npm test` | every push |
| Browser tests (every flow, step counts, no console errors, phone width) | `cd web && E2E_BASE_URL=https://flightscout-app.vercel.app npm run test:e2e` | nightly against the live site |

## Self host your own copy

Everything runs on free tiers (Vercel Hobby, Neon, GitHub Actions). Fork the repo, then:

```sh
vercel login && gh auth login
./scripts/setup.sh my-flightscout you@example.com
```

The script creates both Vercel projects, a Neon database, all secrets (kept in `~/.config/flightscout/deploy-secrets.env`, Vercel and GitHub only), the tracker's GitHub secrets, and deploys. Only `you@example.com` can sign up; add more emails to `ALLOWED_SIGNUP_EMAILS` on Vercel.

## CLI

```sh
curl -fsSL https://raw.githubusercontent.com/halvis82/FlightScout/main/scripts/install-runner.sh | sh   # or: uv tool install ...
flightscout login --url https://<your-site> --token fsk_...   # token from Settings (for watches and history)
flightscout search SAN OSL 2026-11-10 --return 2026-11-20
```

Full reference: [docs/CLI.md](docs/CLI.md). `--sources` takes groups (`google`, `kiwi`, `airlines`, `otas`) or single sources.

Optional keys: `RESEND_API_KEY` + `ALERT_FROM_EMAIL` for email alerts, GitHub or Google OAuth IDs for social login, `SEARCHAPI_KEY`/`SERPAPI_KEY` for the paid Google fallback.
