# FlightScout CLI

The `flightscout` command does everything the website does, plus a few things only a terminal can: CSV and JSON
output for scripts and agents, seller and fare breakdowns from a real browser, and the local runner.

The CLI and the website share one engine (the Python package in `engine/`): the CLI runs it on your computer, the
website calls the same engine on Vercel. When you're logged in, every CLI search is saved to your account and shows up
on the website's History, and the watchlist, places, settings and alerts are the same everywhere.

## Install

```sh
uv tool install --python 3.12 'flightscout[browser] @ git+https://github.com/halvis82/FlightScout#subdirectory=engine'
flightscout setup-browser                     # optional: headless Chromium for --sellers and Google Explore
flightscout login --url https://flightscout-app.vercel.app --token fsk_...   # token: website, Settings, API tokens
flightscout --install-completion              # optional: tab completion
```

Update with the same `uv tool install ... --force` command.

## Conventions

| Thing | Accepted values |
|---|---|
| Dates | `2026-11-20`, `today`, `tomorrow`, `+14` (days from today), `fri` (the next Friday) |
| Airports | codes (`SAN`), lists (`OSL,TRF`), metros: `NYC` `LON` `PAR` `TYO` `CHI` `WAS` `MIL` `ROM` `STO` `OSLX` (OSL, TRF, RYG) `BAY` (SFO, OAK, SJC) `LAXX` (LA area) `MEX` `SEL` `SAO` `BUE` `YTO` `MIA` `HOU` `DFW` `BKK` `SHA` `BJS` `IST` |
| Currency | `-c NOK`, `-c EUR`, `-c USD`, `-c GBP`, `-c MXN` (any ISO code works); default from `flightscout config set --currency` |
| Output | table (default), `--format json` or `--json` (agents, scripts), `--format csv` (spreadsheets) |
| Saving | results are saved to your account when logged in; `--no-save` to skip |
| Links | every result has a booking link; `--open N` opens result N in your browser |

## Recipes

```sh
# Weekend away from Oslo under 1,500 NOK, one command
flightscout explore OSL --weekend --max-price 1500 -c NOK

# Christmas home: flexible dates, cheapest first, include cheaper separate ticket combos
flightscout search SAN OSL 2026-12-18 -r 2027-01-04 --depart-flex 3 --return-flex 2 --smart

# Nonstop mornings only, open the best result
flightscout search SFO JFK +30 --max-stops 0 --time morning --open 1

# Positioning and split tickets: San Diego to Bali via LAX, SFO, Asian hubs
flightscout plan SAN DPS 2027-02-11 -r 2027-02-22

# Multi city with a deadline: be in Paris by Nov 15
flightscout multicity SAN JFK@2026-11-03~2 OSL@2026-11-07~3 CDG@by2026-11-15 SAN@2026-11-20~1

# Cheapest day to fly this month (Google + airline + Skyscanner calendars)
flightscout dates TIJ GDL --from 2026-11-01 --to 2026-11-30 -c MXN

# Who sells it and what the fare includes (bags, changes, refunds)
flightscout search JFK LAX +30 --sellers 3

# Watch straight from a search (same as the website's button; saving twice is a no-op)
flightscout search SAN OSL 2026-12-18 -r 2027-01-04 --watch
flightscout multicity SAN JFK@2026-11-03~2 SAN@2026-11-10~1 --watch

# Airline sites for the flights you found, pre-filled
flightscout search OSL CPH 2026-11-20 --airline-links

# Everything at a glance: login, local runner, scheduled checks
flightscout status

# Track a route, get alerts, see the trend
flightscout watch add SAN OSL --from 2026-12-15 --to 2026-12-20 --nights 10-14 --alert-below 900
flightscout watch check && flightscout watch history 1

# Straight to an airline's own search, pre-filled
flightscout airlines --route OSL-CPH -d 2026-11-20 -r 2026-11-27 --open SK

# Scripts and agents
flightscout search OSL LON +21 --json | jq '.trips[0].tickets[0].booking_url'
flightscout explore SAN --format csv > destinations.csv
```

## AI agents (MCP)

```sh
claude mcp add flightscout -- flightscout mcp
```

Tools: `search_flights`, `plan_routes`, `multicity_trip`, `build_trip`, `explore_destinations`, `price_calendar`,
`find_airports`, `airline_links`, `list_watches`, `add_watch`, `check_watch`, `watch_history`, `list_places`. Agents can also call any command below with `--json`.

## Local runner

`flightscout serve --install` starts the engine at login on `127.0.0.1:8787`. The website detects it and sends your
searches through your own home IP instead of Vercel's servers (more reliable, and it can run Google Explore live).

---

# Command reference

Generated from the code by `engine/scripts/gen_cli_docs.py`. Run `flightscout <command> --help` for the same text.

## `flightscout search`

Search flights across Google Flights (including the long, cheap connections from its Cheapest tab),
Kiwi.com and airlines directly.

```sh
flightscout search SAN OSL 2026-12-18 -r 2027-01-04
flightscout search OSL CPH fri --preset weekend --max-price 1500 -c NOK
flightscout search LAX DPS +60 -r +71 --depart-flex 3 --smart --sort best
```

| Argument / option | Type | Description |
|---|---|---|
| `ORIGIN` | argument, required | From: airport codes or metro, comma separated (SAN, OSL,TRF, NYC, BAY). |
| `DESTINATION` | argument, required | To: airport codes or metro. |
| `DEPART` | argument, required | Departure: YYYY-MM-DD, today, tomorrow, +N or a weekday (fri). |
| `--return`, `-r` | str | Return date (omit for one way). |
| `--preset`, `-p` | choice | weekend (next Fri to Sun), week or 2weeks. |
| `--flex` | int | ± days on both dates. |
| `--depart-flex` | int | ± days on the departure only. |
| `--return-flex` | int | ± days on the return only. |
| `--cabin` | choice (default `economy`) | economy, premium, business or first. |
| `--adults` | int range (default `1`) | Passengers (adults), 1 to 9. Prices are for all of them. |
| `--max-stops` | int | 0 for nonstop only. |
| `--nearby` | int | Also search airports within this many km (SAN adds TIJ). |
| `--smart` | flag | Also look for cheaper separate ticket combinations (slower). |
| `--sources` | str (default `default`) | default (google, kiwi, kiwiweb, airlines, otas), or a list. Groups: airlines = every direct airline that flies the route, otas = booking sites (Booking.com, Expedia, KAYAK, Priceline, Trip.com...). Or single sources like google,kiwiweb,jetblue,booking. Browser ones need Chrome (headless); FLIGHTSCOUT_BROWSER=0 turns them off. |
| `--max-price` | float | Hide results above this price. |
| `--sort` | choice (default `price`) | price, duration, departure or best (price + time). |
| `--time` | choice | morning, afternoon or evening departure. |
| `--airline` | str | Only results with this airline (IATA, e.g. SK). |
| `--no-self-transfer` | flag | Hide self transfer itineraries. |
| `--sellers` | int | Seller and fare breakdown for the top N Google results (browser). |
| `--open` | int | Open the booking page of result N in your browser. |
| `--airline-links` | flag | Also print links to each airline's own site, pre-filled. |
| `--watch` | flag | Also add this search to your watchlist (same as the website button). |
| `--limit` | int (default `15`) | Rows to show. |
| `--currency`, `-c` | str | NOK, EUR, USD, GBP, MXN... Default: your configured currency. |
| `--format`, `-f` | choice (default `table`) | table (default), json (for agents and scripts) or csv. |
| `--json` | flag | Shortcut for --format json. |
| `--save`, `--no-save` | flag (default `True`) | Save the result to your web account (History) when logged in. |

## `flightscout plan`

Cheaper routes from separate tickets: split tickets, stopovers, nested round trips and positioning
flights through hubs and gateways near you (e.g. San Diego via LAX).

```sh
flightscout plan SAN DPS 2027-02-11 -r 2027-02-22
flightscout plan OSL SAN +40 --hubs JFK,KEF --max-stopover-days 2
```

| Argument / option | Type | Description |
|---|---|---|
| `ORIGIN` | argument, required | From (airports or metro). |
| `DESTINATION` | argument, required | To (airports or metro). |
| `DEPART` | argument, required | Earliest departure date. |
| `--depart-end` | str | Latest departure date. |
| `--return`, `-r` | str | Earliest return date (round trip). |
| `--return-end` | str | Latest return date. |
| `--hubs` | str | Extra hubs to always try, e.g. JFK,LHR. |
| `--max-hubs` | int (default `8`) | How many hubs to try (more = slower). |
| `--max-stopover-days` | int (default `3`) | Longest stay at a hub between tickets. |
| `--min-connection` | float (default `3.0`) | Hours needed between separate tickets. |
| `--max-trip-days` | int | Longest whole trip. |
| `--max-travel-hours` | float | Longest travel time per direction. |
| `--nested`, `--no-nested` | flag (default `True`) | Try nested round trips (A-hub return + hub-B return). |
| `--value-of-time` | float (default `15.0`) | Money per hour of travel, for ranking. |
| `--cabin` | choice (default `economy`) | economy, premium, business or first. |
| `--adults` | int range (default `1`) | Passengers (adults), 1 to 9. Prices are for all of them. |
| `--max-price` | float |  |
| `--sort` | choice (default `best`) | best (default), price, duration or departure. |
| `--limit` | int (default `20`) |  |
| `--currency`, `-c` | str | NOK, EUR, USD, GBP, MXN... Default: your configured currency. |
| `--format`, `-f` | choice (default `table`) | table (default), json (for agents and scripts) or csv. |
| `--json` | flag | Shortcut for --format json. |
| `--save`, `--no-save` | flag (default `True`) | Save the result to your web account (History) when logged in. |

## `flightscout multicity`

Multi city trip in a fixed order, each flight with its own date window.

```sh
flightscout multicity SAN JFK@2026-11-03±2 OSL@2026-11-07±3 CDG@by2026-11-15 SAN@2026-11-20±1
```

| Argument / option | Type | Description |
|---|---|---|
| `START` | argument, required | Where the trip starts (airport or metro). |
| `LEGS` | argument, required | Stops in order: PLACE@DATE, optionally ±N days (JFK@2026-11-03±2) or 'by' for arrive by (CDG@by2026-11-15). Use ~N instead of ±N if your shell prefers. |
| `--currency`, `-c` | str | NOK, EUR, USD, GBP, MXN... Default: your configured currency. |
| `--cabin` | choice (default `economy`) | economy, premium, business or first. |
| `--adults` | int range (default `1`) | Passengers (adults), 1 to 9. Prices are for all of them. |
| `--min-gap` | float (default `4.0`) | Hours needed between landing and the next flight. |
| `--watch` | flag | Also add this multi city trip to your watchlist. |
| `--limit` | int (default `10`) |  |
| `--format`, `-f` | choice (default `table`) | table (default), json (for agents and scripts) or csv. |
| `--json` | flag | Shortcut for --format json. |
| `--save`, `--no-save` | flag (default `True`) | Save the result to your web account (History) when logged in. |

## `flightscout trip`

Build a trip through several places, letting FlightScout choose the order and dates.

```sh
flightscout trip OSL -s NYC:2-4 -s SAN:5-10 -s MEX:3-5 --from 2026-11-10 --to 2026-11-14
```

| Argument / option | Type | Description |
|---|---|---|
| `START` | argument, required | Home airport the trip starts from. |
| `--stop`, `-s` | str | PLACE or PLACE:MIN-MAX nights, repeatable. |
| `--from` | str | Earliest departure. |
| `--to` | str | Latest first departure. |
| `--end` | str | Where the trip ends (default: start). |
| `--keep-order` | flag | Visit stops in the given order. |
| `--max-trip-days` | int |  |
| `--adults` | int range (default `1`) | Passengers (adults), 1 to 9. Prices are for all of them. |
| `--currency`, `-c` | str | NOK, EUR, USD, GBP, MXN... Default: your configured currency. |
| `--format`, `-f` | choice (default `table`) | table (default), json (for agents and scripts) or csv. |
| `--json` | flag | Shortcut for --format json. |
| `--save`, `--no-save` | flag (default `True`) | Save the result to your web account (History) when logged in. |

## `flightscout dates`

Cheapest price per departure date: Google Flights plus airline and Skyscanner calendars.

```sh
flightscout dates OSL SAN --from 2026-11-01 --to 2026-11-30
flightscout dates TIJ GDL --from +10 --to +40 -c MXN
```

| Argument / option | Type | Description |
|---|---|---|
| `ORIGIN` | argument, required | From. |
| `DESTINATION` | argument, required | To. |
| `--from` | str (default `+7`) | First departure date to price. |
| `--to` | str (default `+37`) | Last departure date (max 60 days after --from). |
| `--trip-days` | int | Round trips of this many nights. |
| `--currency`, `-c` | str | NOK, EUR, USD, GBP, MXN... Default: your configured currency. |
| `--format`, `-f` | choice (default `table`) | table (default), json (for agents and scripts) or csv. |
| `--json` | flag | Shortcut for --format json. |

## `flightscout explore`

Cheapest places to go from ORIGIN (Google Explore, Kiwi, KAYAK, Ryanair).

```sh
flightscout explore SAN --weekend --max-price 200
flightscout explore OSL --from 2026-11-01 --to 2026-11-30 --nights 5-9 -c NOK
flightscout explore OSL --one-way --country ES
```

| Argument / option | Type | Description |
|---|---|---|
| `ORIGIN` | argument, required | Where you start (airport or metro, e.g. SAN or OSLX). |
| `--from` | str (default `+7`) | Earliest departure. |
| `--to` | str (default `+60`) | Latest departure. |
| `--nights` | str | Round trips of MIN-MAX nights (e.g. 2-3 weekend, 5-9 a week). |
| `--weekend` | flag | Shortcut: 2-3 night trips. |
| `--one-way` | flag | One way flights instead of round trips. |
| `--max-price` | float | Only places under this price. |
| `--country` | str | Only this country (ISO code, e.g. MX, IT). |
| `--deep` | flag | Also run the slower region by region lookups. |
| `--regions` | str | Custom regions or countries for --deep, e.g. 'Europe,Mexico'. |
| `--sort` | str (default `price`) | price or date. |
| `--open` | int | Open the booking page of row N. |
| `--limit` | int (default `40`) |  |
| `--currency`, `-c` | str | NOK, EUR, USD, GBP, MXN... Default: your configured currency. |
| `--format`, `-f` | choice (default `table`) | table (default), json (for agents and scripts) or csv. |
| `--json` | flag | Shortcut for --format json. |
| `--save`, `--no-save` | flag (default `True`) | Save the result to your web account (History) when logged in. |

## `flightscout airports`

Look up airports, or list the ones near an airport.

| Argument / option | Type | Description |
|---|---|---|
| `QUERY` | argument, required | Code, city or name (accents optional: cancun). |
| `--nearby` | int | Instead list airports within N km of QUERY. |
| `--format`, `-f` | choice (default `table`) | table (default), json (for agents and scripts) or csv. |
| `--json` | flag | Shortcut for --format json. |

## `flightscout airlines`

Airline directory: go straight to an airline's own search, pre-filled with your route.

```sh
flightscout airlines --region nordics
flightscout airlines --route OSL-CPH -d 2026-11-20 -r 2026-11-27 --open SK
flightscout airlines "free carry-on" --category budget
```

| Argument / option | Type | Description |
|---|---|---|
| `QUERY` | argument, optional | Name, code or tag (e.g. 'free carry-on'). Empty lists all. |
| `--region` | str | global, nordics, europe, us_domestic, north_america, mexico, central_america_caribbean, south_america, middle_east, africa, asia, oceania. |
| `--category` | str | budget, full_service, low_cost, ultra_low_cost, regional... |
| `--alliance` | str | star, oneworld, skyteam or none. |
| `--route` | str | FROM-TO to get pre-filled search links, e.g. OSL-CPH. |
| `--depart`, `-d` | str | Departure date for --route. |
| `--return`, `-r` | str | Return date for --route. |
| `--open` | str | Open this airline's search (IATA code) in the browser. |
| `--format`, `-f` | choice (default `table`) | table (default), json (for agents and scripts) or csv. |
| `--json` | flag | Shortcut for --format json. |

## `flightscout watch`

Watchlist: routes tracked twice a day, with price history and alerts.

## `flightscout places`

Saved places: homes, favorites and places you want to go.

## `flightscout login`

Connect the CLI and MCP server to your account.

| Argument / option | Type | Description |
|---|---|---|
| `--url` | str | Your FlightScout site, e.g. https://flightscout-app.vercel.app. |
| `--token` | str | API token (website: Settings, API tokens). |

## `flightscout logout`

Forget the saved token.

## `flightscout whoami`

Show the connected account and its settings.

| Argument / option | Type | Description |
|---|---|---|
| `--format`, `-f` | choice (default `table`) | table (default), json (for agents and scripts) or csv. |
| `--json` | flag | Shortcut for --format json. |

## `flightscout open`

Open the website in your browser.

| Argument / option | Type | Description |
|---|---|---|
| `PAGE` | argument, optional | Page: search (default), airlines, settings, history. |

## `flightscout settings`

Account settings (same as the website's Settings page).

## `flightscout alerts`

Price alerts from your watches.

## `flightscout history`

Past searches from the website, CLI and agents.

## `flightscout tokens`

API tokens for the CLI, MCP server and scripts.

## `flightscout config`

Local CLI configuration (~/.config/flightscout/config.json).

## `flightscout serve`

Local runner: the website sends searches to this computer, so they come from your own IP and can use the
browser read airlines and booking sites. Runs only while you use it.

| Argument / option | Type | Description |
|---|---|---|
| `--port` | int (default `8787`) | Port (the website looks for 8787). |
| `--install` | flag | Start on demand: the system listens on the port and starts the runner when the website calls it (macOS launchd, Linux systemd). Nothing runs while you're not searching. |
| `--idle` | int | Exit after this many minutes without searches (0 = never). --install uses 10. |
| `--track`, `--no-track` | flag | With --install on macOS: also check your watches at 07:05 and 19:05 from this Mac (a few minutes twice a day). |
| `--uninstall` | flag | Remove the on demand runner and scheduled checks. |

## `flightscout mcp`

MCP server on stdio for AI agents: `claude mcp add flightscout -- flightscout mcp`.

## `flightscout setup-browser`

Install the headless Chromium used by --sellers and Google Explore.

## `flightscout track`

Check every user's watches (GitHub Actions job; needs FLIGHTSCOUT_TRACKER_KEY).

| Argument / option | Type | Description |
|---|---|---|
| `--budget` | int (default `12`) | Google searches per watch. |
| `-v` | flag |  |

## `flightscout warm`

Pre-compute explore results for everyone's home airports into the shared cache (GitHub Actions job).

| Argument / option | Type | Description |
|---|---|---|
| `--currency` | str (default `USD`) |  |
| `-v` | flag |  |

## `flightscout status`

Login, local runner, scheduled watch checks and browser support at a glance.

## `flightscout local`

The whole FlightScout on this computer, running only while it's open in your browser.
