# FlightScout

End to end flight finder for people who fly a lot. It searches Google Flights, Kiwi.com, Volaris and Ryanair together, builds cheaper routes out of separate tickets (self transfers, stopovers, nested round trips, multi city trips), shows where you can go cheaply, and tracks the routes you care about twice a day so you get price history and alerts. Every result links straight to the page where you can book it.

Three ways to use it, all sharing one account and database:

| | |
|---|---|
| **Website** | https://flightscout-app.vercel.app. Works as a guest (data kept in your browser) or signed in (sync, background tracking, alerts) |
| **CLI** | `flightscout search / plan / trip / explore / dates / watch ...` with `--json` for scripts and agents |
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
| Kiwi.com | public MCP endpoint | Self transfer combinations, flexible date ranges, "anywhere" and region explore |
| Volaris | volaris.com backend | Volaris fares Google doesn't price (most Mexican routes), fare calendar |
| Ryanair | fare finder API | Cheap destinations from Ryanair bases |
| SerpApi (optional) | paid API, `SERPAPI_KEY` | Fallback if Google blocks the server |

Scraping is unofficial and can break. Searches are cached, Kiwi is throttled, and the site can route searches through your own computer (local runner) so they come from a normal home IP instead of a datacenter.

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
