# FlightScout engine

Python package `flightscout`: sources, route planner, explore, tracker, CLI, MCP server and the HTTP API used by the web app.

## Install the CLI

```sh
uv tool install --force /Users/halvis82/Documents/personal_coding/FlightScout/engine
flightscout login --url https://<your-site>.vercel.app --token fsk_...   # token from Settings, API tokens
```

Reinstall with the same command after pulling changes.

## Commands (add `--json` for machine readable output)

| Command | What it does |
|---|---|
| `flightscout search OSL SAN 2026-11-20 -r 2026-12-04 -c NOK` | One ticket itineraries from Google Flights + Kiwi |
| `flightscout plan OSL SAN 2026-11-20 -r 2026-12-04 --hubs JFK --max-stopover-days 3` | Split tickets, stopovers and nested round trips via hubs |
| `flightscout trip OSL -s NYC:2-4 -s SAN:5-10 --from 2026-11-10 --to 2026-11-14` | Multi city trip builder (order optimized unless `--keep-order`) |
| `flightscout explore OSL --from +7 --to +60 --nights 3-7` | Cheapest destinations (Kiwi regions + Ryanair) |
| `flightscout dates OSL SAN --from 2026-11-01 --to 2026-11-30` | Cheapest price per date (Google) |
| `flightscout airports "san diego"` | Airport lookup |
| `flightscout watch add OSL SAN --from 2026-12-15 --to 2026-12-22 --nights 10-14` | Track a route |
| `flightscout watch list / check / history <id> / rm <id>` | Manage and run tracking |
| `flightscout places list / add "Home" SAN --kind home` | Saved places |
| `flightscout open watchlist` | Open the web app |
| `flightscout mcp` | MCP server on stdio |

Dates accept `YYYY-MM-DD`, `today`, `tomorrow` or `+N` days. Airports accept metro codes: NYC, LON, PAR, TYO, CHI, WAS, MIL, ROM, STO, OSLX (OSL/TRF/RYG), BAY (SFO/OAK/SJC), LAXX (LAX/BUR/LGB/SNA/ONT), MEX, SEL, SAO, and more (`airports.py`).

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
| Ryanair | fare finder API | Explore from Ryanair bases |
| Volaris | volaris.com backend (Navitaire), Chrome TLS impersonation | Google has no Volaris prices for most Mexican routes. Prices include the TUA airport fee |
| SerpApi | optional, `SERPAPI_KEY` | Paid fallback (250 free searches/month) |

## HTTP API

`uvicorn flightscout.api:app --port 8787` (with `PYTHONPATH=src`). Deployed to Vercel from this folder (`app.py`). Set `ENGINE_KEY`.

## Dev note (macOS)

Something on this Mac marks files in `.venv` as hidden, and Python then skips `.pth` files, so the editable install isn't found. Use `PYTHONPATH=src uv run ...` or run `chflags nohidden .venv/lib/python3.12/site-packages/*.pth`.
