# FlightScout

End to end flight finder for people who fly a lot. It searches Google Flights, Kiwi.com and airlines directly (Volaris, Widerøe, Sky Airline, Norse, Volotea, Condor, plus fare calendars from Wizz Air, VivaAerobus and Ryanair) together, builds cheaper routes out of separate tickets (self transfers, stopovers, nested round trips, multi city trips), shows where you can go cheaply, and tracks the routes you care about twice a day so you get price history and alerts. Every result links straight to the page where you can book it.

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
   └──▶ local runner (optional, `flightscout serve` on your computer: same engine, your home IP)

GitHub Actions (twice a day) ── engine + headless browser ──▶ web /api/v1/tracker (price history, alerts)
```

Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [engine/README.md](engine/README.md), [web/README.md](web/README.md).

## Data sources

| Source | Method | Coverage |
|---|---|---|
| Google Flights | [fli](https://github.com/punitarani/fli) reads the data embedded in the results page | Almost every airline. Booking link opens Google's page for the exact itinerary with the airline's own "Book" button |
| Google booking page | headless browser (CLI and tracker only) | Every seller for an itinerary (airline or agency), fare families, bag fees, change and refund rules, Google's typical price range |
| Kiwi.com | public MCP endpoint and the GraphQL backend of kiwi.com | Self transfer combinations, flexible date ranges, "anywhere" and region explore, per day calendar |
| KAYAK Explore, Skyscanner calendar | the JSON behind kayak.com/explore and Skyscanner's month view | Fast "anywhere" leads and cached per day fares that Google often misses |
| Volaris | volaris.com backend | Volaris fares Google doesn't price (most Mexican routes), fare calendar |
| Ryanair | fare finder API | Cheap destinations from Ryanair bases |
| Widerøe | wideroe.no booking page data | Real Widerøe fares (Google has none or badly overpriced ones) |
| Sky Airline | Sky's web API (`FLIGHTSCOUT_SKY_KEYS`) | Chile and Peru; Google has no Sky prices |
| Norse, Condor | their web APIs | Transatlantic low cost; not sold by Kiwi |
| Volotea | Volotea's web API (`FLIGHTSCOUT_VOLOTEA_KEY`) + public schedule | Seasonal European routes |
| Wizz Air, VivaAerobus (`FLIGHTSCOUT_VIVA_KEY`) | fare calendars | Cheapest fare per day in the date picker |
| Flair (opt-in) | Flair's web API | Same prices as Google, enable with `--sources` |

Some airline sources need the public key their own website sends to every browser. Those keys aren't kept in this repo; set the env vars shown (find them in your browser's dev tools on the airline's site). Without them those sources simply stay off.

The Airlines tab lists 127 airlines by region with links into each airline's own search, pre-filled with your route where the airline supports it.
| SerpApi (optional) | paid API, `SERPAPI_KEY` | Fallback if Google blocks the server |

### Staying unblocked (whose IP talks to Google)

Scraping is unofficial and Google limits how often one address can search, so FlightScout spreads the load:

| Layer | What it does |
|---|---|
| **FlightScout Helper** (browser extension, `extension/`) | Google Flights pages are fetched by each visitor's own browser and IP; the server only parses them. Searches and price calendars. |
| **Local runner** (`flightscout serve --install`) | The whole engine on your computer: the site sends searches there. Also checks your watches at 07:05 and 19:05 from your home IP. |
| **Shared cache** | The same search by anyone within minutes (20 min searches, 6 h calendars) is answered from the database. |
| **Fast non Google sources** | Kiwi web API, KAYAK, Skyscanner and airline APIs are used wherever possible. |
| **Paid fallback (optional)** | If Google blocks the server, searches switch to SearchAPI.io (`SEARCHAPI_KEY`) or SerpApi (`SERPAPI_KEY`) when a key is set; nothing is spent otherwise. |
| **Self hosting** | `scripts/setup.sh` gives anyone their own copy on their own accounts. |

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

## CLI and local runner

```sh
uv tool install --python 3.12 'flightscout[browser] @ git+https://github.com/halvis82/FlightScout#subdirectory=engine'
flightscout setup-browser                      # headless Chromium for --sellers
flightscout login --url https://<your-site> --token fsk_...   # token from Settings
flightscout serve --install                    # local runner, starts at login
```

Optional keys: `RESEND_API_KEY` + `ALERT_FROM_EMAIL` for email alerts, GitHub or Google OAuth IDs for social login, `SERPAPI_KEY` as a GitHub secret for the paid fallback.
