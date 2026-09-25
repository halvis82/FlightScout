# FlightScout engine

Python package `flightscout`: sources, route planner, explore, tracker, CLI, MCP server and the HTTP API used by the web app.

## Install the CLI

```sh
uv tool install --force /Users/halvis82/Documents/personal_coding/FlightScout/engine
flightscout login --url https://<your-site>.vercel.app --token fsk_...   # token from Settings, API tokens
```

Reinstall with the same command after pulling changes.

## Commands

Full CLI guide and reference: [docs/CLI.md](../docs/CLI.md) (generated from the code, checked in CI).

Main commands: `search`, `plan`, `multicity`, `trip`, `dates`, `explore`, `airports`, `airlines`, `watch`, `places`,
`settings`, `alerts`, `history`, `tokens`, `login`, `serve`, `mcp`. Every command takes `--help`, and result commands
take `--format json|csv`.

## Use from AI agents

```sh
claude mcp add flightscout -- flightscout mcp
```

Tools: `search_flights`, `plan_routes`, `build_trip`, `explore_destinations`, `price_calendar`, `find_airports`, `list_watches`, `add_watch`, `watch_history`, `list_places`. When the CLI is logged in, every agent search is saved to the web app's History page.

## Sources

| Source | How | Notes |
|---|---|---|
| Google Flights | [fli](https://github.com/punitarani/fli) (page embedded data) | Per itinerary booking links; rate limited from datacenter IPs |
| Kiwi.com | public MCP endpoint `https://mcp.kiwi.com` | Self transfer fares, date ranges, region explore; 15 results per call |
| Kiwi.com web backend (`kiwiweb`) | GraphQL behind kiwi.com (`api.skypicker.com/umbrella/v2/graphql`), keyless, Chrome TLS | Up to 100 itineraries per call, several airports per side, one call "anywhere" explore (one cheapest trip per city), per day calendar |
| KAYAK Explore (`kayak`) | JSON behind kayak.com/explore, keyless | 100 to 400 destinations per call in under 2 s. Cached round trip fares, priced in the currency of the matching KAYAK domain |
| Skyscanner calendar (`skyscanner`) | month view grid behind skyscanner.net, keyless | Cheapest cached one way fare per day for any route, often below Google (OTA quotes for Frontier, Volaris, Wizz). Cells older than 10 days dropped |
| Ryanair | fare finder API | Explore from Ryanair bases |
| Volaris | volaris.com backend (Navitaire), Chrome TLS impersonation | Google has no Volaris prices for most Mexican routes. Prices include the TUA airport fee |
| SerpApi | optional, `SERPAPI_KEY` | Paid fallback (250 free searches/month) |

### Browser airlines

Airlines that block plain HTTP clients are read through one shared real Google Chrome per process
(`sources/_browser.py`: Chrome started by us and attached over CDP, one worker thread per browser, closed when idle
or at exit). They are not in the default source list (Vercel has no browser); `search()` adds them by itself when
Playwright (`--extra browser`) and Chrome are installed, so the local runner, the CLI and the GitHub tracker get them.
`FLIGHTSCOUT_BROWSER=0` turns them off, `FLIGHTSCOUT_CHROME` points at a Chrome binary.

| Source | How | Notes |
|---|---|---|
| Transavia (`transavia`) | booking deeplink, then the site's `/start/api/flight-availability` JSON opened as a page | Headless, 1 to 3 s. Cloudflare blocks the page's own XHR but not document loads. Fills routes Google and Kiwi miss (Orly to Lisbon or Porto) |
| Norwegian (`norwegian`) | `/en/start/booking/avaday/` deeplink, captures the Amadeus `air-bounds` JSON | Headless, 3 to 9 s. Round trips priced as two one ways |
| Southwest (`southwest`) | select-depart deeplink, captures the `shopping` JSON | Headless, 3 to 6 s. Southwest is not on OTAs |
| VivaAerobus (`vivaaerobus`) | booking deeplink, captures `availability/search` | Headful (Akamai blocks headless), window off screen and minimized, 5 to 9 s. Skipped without a display |
| Allegiant (`allegiant`) | results deeplink, captures the `flights` GraphQL response | Headful (Cloudflare Turnstile), 2 to 6 s. Routes from `data/allegiant_routes.json` |

## HTTP API

`uvicorn flightscout.api:app --port 8787` (with `PYTHONPATH=src`). Deployed to Vercel from this folder (`app.py`). Set `ENGINE_KEY`.

## Dev note (macOS)

Something on this Mac marks files in `.venv` as hidden, and Python then skips `.pth` files, so the editable install isn't found. Use `PYTHONPATH=src uv run ...` or run `chflags nohidden .venv/lib/python3.12/site-packages/*.pth`.
