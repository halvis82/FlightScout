# Sources

Generated from `engine/src/flightscout/search.py` by `engine/scripts/gen_sources_doc.py`. Every source's prices were checked against that site's own booking page when it was added; the live tests (`FLIGHTSCOUT_LIVE=1 uv run pytest -m live`) keep checking them.

## Google Flights, Kiwi (3)

Runs on: server, extension (Google) or local runner.

| Source | Notes |
|---|---|
| `google` | Google Flights via the ``fli`` library (reads the data embedded in the results page, so it survives Google's August 2026 API lockdown). |
| `kiwi` | Kiwi.com through its public MCP endpoint (https://mcp.kiwi.com, keyless). Kiwi is the main source of self transfer (virtual interlining) fares, flexible date ranges and "anywhere" exploration. |
| `kiwiweb` | Kiwi.com through the GraphQL backend its own website uses (api.skypicker.com/umbrella/v2/graphql, keyless, Chrome TLS impersonation). |

## Airlines direct, plain HTTP (25)

Runs on: server or local runner.

| Source | Notes |
|---|---|
| `volaris` | Volaris (Y4) direct from volaris.com's own backend (Navitaire dotREZ at apigw.volaris.com). Google Flights has Volaris schedules but no prices for most of its Mexican routes, so this source fills a real gap. |
| `wideroe` | Widerøe (WF) direct from wideroe.no. Google Flights has most Widerøe schedules but usually no price (the regional PSO network especially), and Kiwi only has part of it, so this source fills a real gap. |
| `skyairline` | Sky Airline (H2) direct from skyairline.com's own booking backend (api.skyairline.com, an Azure APIM gateway in front of their Sabre based shopping). Google Flights has Sky schedules but no prices, so this source fills a... |
| `norse` | Norse Atlantic Airways direct from flynorse.com's own backend (Navitaire dotREZ behind services.flynorse.com). Norse flies as N0 (Norway) and Z0 (UK, all Gatwick flights). Google Flights prices Norse correctly (LGW-MCO $... |
| `volotea` | Volotea (V7) direct from volotea.com's own backend (Navitaire dotREZ behind api.volotea.com). Google Flights prices Volotea's regular fare correctly, but Kiwi misses many Volotea nonstops, and Volotea is highly seasonal,... |
| `condor` | Condor (DE) direct from condor.com's own flight API (data.condor.com). Kiwi does not sell Condor at all. Google prices Condor's own flights correctly (FRA-JFK $619.99 and FRA-LPA $338.99, identical here, in the September... |
| `flair` | Flair Airlines (F8) direct from flyflair.com's own Next.js API routes (/api/flair-flights/*, a proxy in front of Navitaire). Google Flights already prices Flair and agreed with this source to the dollar in tests, so this... |
| `frontier` | Frontier (F9) direct from flyfrontier.com. The booking site is server rendered (Navitaire): GET /Flight/InternalSelect, the URL the search form itself opens, answers with the select page, and the page carries every fligh... |
| `breeze` | Breeze Airways (MX) direct from flybreeze.com's own GraphQL backend (api.flybreeze.com, a layer over Navitaire dotREZ). Breeze sells mostly on its own site and Google often lacks its fares, so this fills a real gap. |
| `jetblue` | JetBlue (B6) direct from jetblue.com's own flight search API, the one the results page calls: POST /api/ecom/cb-flight-search/v1/search/NGB. Plain HTTP with Chrome TLS impersonation (curl_cffi) is enough for the API (the... |
| `alaska` | Alaska Airlines (AS) and Hawaiian Airlines (HA, same booking site since the merger) direct from alaskaair.com. The results page is SvelteKit: its own data endpoint (/search/results/__data.json?<same query as the page>) s... |
| `arajet` | Arajet (DM) direct from arajet.com's own shopping API (POST /pss/shop/airshop), the call its booking page makes. Arajet is a Dominican ULCC with connections through Santo Domingo all over the Americas; OTAs and Google of... |
| `aeromexico` | Aeromexico (AM) direct from aeromexico.com's own booking backend (amx-c-bkngbk-pd.aeromexico.com /bc/ow/rt/search/flight), the calls its select flight page makes. Plain HTTP with Chrome TLS impersonation works. |
| `aerolineas` | Aerolíneas Argentinas (AR) direct from aerolineas.com.ar's own shopping API (api.aerolineas.com.ar/v1/flights/offers). Aerolíneas prices in ARS for its Argentine point of sale and Google often shows only USD fares from o... |
| `jet2` | Jet2.com (LS) direct from jet2.com. Jet2 sells only on its own site (no GDS), so Google and Kiwi often miss its fares or show stale ones. |
| `aerlingus` | Aer Lingus (EI) direct from aerlingus.com's own flight search API. |
| `vueling` | Vueling (VY) direct from vueling.com's own booking backend (ams.vueling.com, a Navitaire dotREZ wrapper with a GraphQL availability endpoint). |
| `skyexpress` | SKY express (GQ, Greece) direct from its own booking app (flights.skyexpress.gr, Sabre EzyCommerce). Kiwi and Google carry SKY express only partly (Greek domestic and island hops are thin there), so its own fares fill a ... |
| `jazeera` | Jazeera Airways (J9) direct from jazeeraairways.com. Kuwait based low cost carrier (Gulf, Levant, Egypt, Turkey, Central and South Asia, a few European summer routes) that Kiwi covers only partly. |
| `flysafair` | FlySafair (FA) direct from flysafair.co.za. South Africa's largest low cost carrier (domestic trunk routes plus a few regional ones). Kiwi and Google often show only part of its schedule or stale prices. |
| `airnewzealand` | Air New Zealand (NZ) direct from airnewzealand.co.nz, New Zealand domestic flights only. |
| `biman` | Biman Bangladesh Airlines (BG) direct from booking.biman-airlines.com. Bangladesh's flag carrier (Dhaka hub: Gulf, India, South East Asia, London, Manchester, Rome, Toronto, Tokyo), thinly covered by Kiwi and the OTAs. |
| `flyarystan` | FlyArystan (FS) direct from its Hitit Crane booking engine. Kazakhstan's low cost carrier (Air Astana group): dense domestic network plus Central Asia, the Caucasus, Turkey, the Gulf and India. Kiwi and Google see only p... |
| `starair` | Star Air (S5) direct from its Hitit Crane booking engine (book-sdg.crane.aero). Regional Indian airline (Embraer jets, UDAN routes from Bengaluru, Mumbai, Hyderabad, Ahmedabad, ...) that Kiwi and most OTAs don't sell. |
| `allianceair` | Alliance Air (9I) direct from bookme.allianceair.in. India's state owned regional airline (ATR turboprops on 50 odd airports, many UDAN routes to small towns) that Kiwi and most OTAs don't sell. |

## Airlines direct, headless Chrome (28)

Runs on: local runner only.

| Source | Notes |
|---|---|
| `transavia` | Transavia (HV Netherlands, TO France) direct from transavia.com through the shared real Chrome (see _browser.py). Google and Kiwi only cover part of the Transavia network (Orly to Lisbon or Porto is often missing), so th... |
| `norwegian` | Norwegian (DY, D8) direct from norwegian.com through the shared real Chrome (see _browser.py). Cloudflare shows plain HTTP clients a "Just a moment" challenge; real Chrome (even headless) passes it by itself. |
| `southwest` | Southwest (WN) direct from southwest.com through the shared real Chrome (see _browser.py). Southwest isn't sold by OTAs and Google often shows only some of its fares; its shopping API answers 403 to plain HTTP clients (A... |
| `vivaaerobus` | VivaAerobus (VB) low fare calendar, direct from api.vivaaerobus.com. |
| `allegiant` | Allegiant (G4) direct from allegiantair.com through the shared real Chrome (see _browser.py). Allegiant sells only on its own site (no OTAs, and Google rarely prices it), and Cloudflare challenges plain HTTP clients and ... |
| `avelo` | Avelo Airlines (XP) direct from aveloair.com through the shared headless Chrome (see _browser.py). Avelo sells only on its own site and Google often lacks its fares. The booking app is a Blazor WebAssembly app whose shop... |
| `united` | United Airlines (UA) direct from united.com through the shared real Chrome (see _browser.py). United's shopping API (/api/flight/...) answers 428 "Access Denied" (Akamai) to plain HTTP clients even with a valid anonymous... |
| `porter` | Porter Airlines (PD) direct from flyporter.com through the shared real Chrome (see _browser.py). flyporter.com sits behind Cloudflare, which turns plain HTTP clients away, but headless Chrome gets through. |
| `westjet` | WestJet (WS) direct from westjet.com through the shared real Chrome (see _browser.py). WestJet's shopping API (apiw.westjet.com/ecomm/booktrip/ flight-search-api/v1) is guarded by a bot manager that signs every request f... |
| `caribbean` | Caribbean Airlines (BW) direct from caribbean-airlines.com through the shared real Chrome (see _browser.py). The site hands searches to Amadeus e-Retail (book.bw.amadeus.com/plnext/CaribbeanAirlines), which sits behind I... |
| `caymanairways` | Cayman Airways (KX) direct from caymanairways.com's booking engine (Sabre Digital Experience at flights.caymanairways.com/dx/KXDX) through the shared real Chrome (see _browser.py). Its GraphQL API sits behind a bot manag... |
| `wingo` | Wingo (P5, Copa's low cost arm) direct from wingo.com through the shared real Chrome (see _browser.py). Wingo signs every API call in the browser (a fresh RS256 token per request, delivered over a server sent events chan... |
| `finnair` | Finnair (AY) direct from finnair.com through the shared real Chrome (see _browser.py). Akamai answers plain HTTP clients (even with Chrome TLS) 403 on api.finnair.com, but headless Chrome passes. |
| `afklm` | Air France / KLM (AF, KL and their partners) direct from klm.com through the shared real Chrome (see _browser.py). Both airlines run the same booking engine; the KLM site sells the whole AF-KLM network (KLM and Air Franc... |
| `level` | LEVEL (LL, IAG's long haul low cost from Barcelona) direct from flylevel.com through the shared real Chrome (see _browser.py). Plain HTTP clients get an Akamai "crypto" challenge page on the flight pages (the fare calend... |
| `tap` | TAP Air Portugal (TP, and Portugália NI) direct from booking.flytap.com through the shared real Chrome (see _browser.py). The booking API itself (/bfm/rest/booking/availability/search) answers plain HTTP clients with a 4... |
| `aegean` | Aegean Airlines (A3, and its regional Olympic Air OA) direct from aegeanair.com through the shared real Chrome (see _browser.py). Both the site and the Amadeus booking engine behind it (e-ticket.aegeanair.com) sit behind... |
| `flydubai` | flydubai (FZ) direct from flydubai.com through the shared headless Chrome (see _browser.py). Its booking app (flights2.flydubai.com) sits behind Akamai Bot Manager: plain HTTP clients get "Access Denied" on the flight AP... |
| `qatar` | Qatar Airways (QR) direct from qatarairways.com through the shared real Chrome (see _browser.py). Akamai answers plain HTTP clients with "Access Denied" on the booking API, but headless Chrome gets through. |
| `etihad` | Etihad Airways (EY) direct from etihad.com through the shared real Chrome (see _browser.py). The booking app (digital.etihad.com, Amadeus Digital Experience) sits behind Akamai; headless Chrome gets through, plain HTTP d... |
| `spicejet` | SpiceJet (SG) direct from spicejet.com through the shared real Chrome (see _browser.py). Akamai answers 403 to plain HTTP clients on the search API (the home page and the anonymous token work, the availability call does ... |
| `akasa` | Akasa Air (QP) direct from akasaair.com through the shared real Chrome (see _browser.py). The booking backend (prod-bl.qp.akasaair.com, Navitaire dotREZ behind a thin "ibe" API) answers 403 to plain HTTP clients, token c... |
| `vietjet` | VietJet (VJ, and Thai VietJet VZ) direct from vietjetair.com through the shared real Chrome (see _browser.py). The search API signs every request (HMAC headers computed by the page's JS) and sits behind AWS WAF plus an i... |
| `tigerair` | Tigerair Taiwan (IT) direct from tigerairtw.com through the shared real Chrome (see _browser.py). Google Flights shows Tigerair Taiwan but often without a price, and Kiwi only sells part of its network. |
| `zipair` | ZIPAIR (ZG) direct from zipair.net through the shared real Chrome (see _browser.py). ZIPAIR sells only on its own site (no GDS), so Google and Kiwi often lack its fares, including its self sold connections via Narita. |
| `jejuair` | Jeju Air (7C) direct from jejuair.net through the shared real Chrome (see _browser.py). Korea's biggest low cost carrier; Google Flights often shows it without a price and Kiwi only sells part of its network. |
| `virginaustralia` | Virgin Australia (VA) direct from virginaustralia.com through the shared real Chrome (see _browser.py). The booking app (Sabre Digital Experience, book.virginaustralia.com/dx/VADX) sits behind Imperva, which answers plai... |
| `fly91` | FLY91 (IC) direct from fly91.in through the shared headless Chrome (see _browser.py). Goa based regional airline (ATR 72s from Goa Mopa, Pune, Hyderabad, Bengaluru, Sindhudurg, Jalgaon, Agatti, ...) that Kiwi and most OT... |

## Booking sites, plain HTTP (11)

Runs on: server or local runner.

| Source | Notes |
|---|---|
| `booking` | Booking.com Flights (flights.booking.com, fares and ticketing by Etraveli, the Gotogate / Mytrip group) through the JSON endpoint its own results page calls: /api/flights/ (keyless, Chrome TLS impersonation, plain HTTP). |
| `kayakweb` | KAYAK flight search results (the full itinerary search, not Explore) and its sister metasearch sites on the same platform, momondo and Cheapflights, over plain HTTP (keyless, Chrome TLS impersonation). |
| `momondo` | KAYAK flight search results (the full itinerary search, not Explore) and its sister metasearch sites on the same platform, momondo and Cheapflights, over plain HTTP (keyless, Chrome TLS impersonation). |
| `cheapflights` | KAYAK flight search results (the full itinerary search, not Explore) and its sister metasearch sites on the same platform, momondo and Cheapflights, over plain HTTP (keyless, Chrome TLS impersonation). |
| `expedia` | Expedia Group flight search (Expedia, Orbitz, Travelocity) through the GraphQL query their own results page runs (FlightsSearchResultsLoadedQuery, a persisted query on /graphql). |
| `orbitz` | Expedia Group flight search (Expedia, Orbitz, Travelocity) through the GraphQL query their own results page runs (FlightsSearchResultsLoadedQuery, a persisted query on /graphql). |
| `travelocity` | Expedia Group flight search (Expedia, Orbitz, Travelocity) through the GraphQL query their own results page runs (FlightsSearchResultsLoadedQuery, a persisted query on /graphql). |
| `priceline` | Priceline (US OTA) flight search results, keyless. |
| `wego` | Wego (metasearch, strongest in the Middle East and Asia) through the JSON API its own website polls (srv.wego.com/v2/metasearch, keyless, Chrome TLS impersonation, no browser). |
| `gotogate` | Gotogate (and its sister brand Mytrip, see mytrip.py), both Etraveli Group OTAs, through the GraphQL endpoint their own result page calls (POST /graphql/SearchOnResultPage, keyless, Chrome TLS impersonation). About one s... |
| `mytrip` | Mytrip, Etraveli Group's sister brand of Gotogate: same backend and GraphQL endpoint (see gotogate.py), its own prices and booking pages. |

## Booking sites, headless Chrome (7)

Runs on: local runner only.

| Source | Notes |
|---|---|
| `tripcom` | Trip.com flights through the shared headless Chrome (see _browser.py). |
| `aviasales` | Aviasales (metasearch, the Travelpayouts flagship) live search through the shared real Chrome (see _browser.py). |
| `edreams` | eDreams (and Opodo, see opodo.py), the eDreams ODIGEO OTAs, through the shared real Chrome (see _browser.py). Their search GraphQL call (frontend-api/service/graphql, searchItinerary) only answers inside a browser sessio... |
| `opodo` | Opodo, eDreams ODIGEO's sister brand of eDreams: same platform and search call (see edreams.py), its own prices and booking pages (opodo.co.uk, GBP). |
| `almosafer` | Almosafer (Saudi Arabia / Gulf OTA, Seera Group) through the shared real Chrome (see _browser.py). Its search API wants a session token the page mints, so we open the site's own one way results page headless and read the... |
| `traveloka` | Traveloka (Southeast Asia OTA) through the shared real Chrome (see _browser.py). Plain HTTP clients get DataDome and AWS WAF challenges; a headless Chrome passes them. We open the site's own one way results page (en-id, ... |
| `cleartrip` | Cleartrip (India OTA, Flipkart group) through the shared real Chrome (see _browser.py). Its search API sits behind Akamai (plain HTTP gets "Access Denied"), so we open the site's own one way results page headless and cap... |

## Fare calendars (11)

Runs on: server or local runner (browser ones local only).

| Source | Notes |
|---|---|
| `volaris` | Volaris (Y4) direct from volaris.com's own backend (Navitaire dotREZ at apigw.volaris.com). Google Flights has Volaris schedules but no prices for most of its Mexican routes, so this source fills a real gap. |
| `vivaaerobus` | VivaAerobus (VB) low fare calendar, direct from api.vivaaerobus.com. |
| `wizzair` | Wizz Air (W6) low fare calendar from wizzair.com's own backend (be.wizzair.com/<build>/Api). Keyless, but requests must look like Chrome at the TLS level (curl_cffi impersonation). |
| `volotea` | Volotea (V7) direct from volotea.com's own backend (Navitaire dotREZ behind api.volotea.com). Google Flights prices Volotea's regular fare correctly, but Kiwi misses many Volotea nonstops, and Volotea is highly seasonal,... |
| `skyairline` | Sky Airline (H2) direct from skyairline.com's own booking backend (api.skyairline.com, an Azure APIM gateway in front of their Sabre based shopping). Google Flights has Sky schedules but no prices, so this source fills a... |
| `flair` | Flair Airlines (F8) direct from flyflair.com's own Next.js API routes (/api/flair-flights/*, a proxy in front of Navitaire). Google Flights already prices Flair and agreed with this source to the dollar in tests, so this... |
| `norse` | Norse Atlantic Airways direct from flynorse.com's own backend (Navitaire dotREZ behind services.flynorse.com). Norse flies as N0 (Norway) and Z0 (UK, all Gatwick flights). Google Flights prices Norse correctly (LGW-MCO $... |
| `level` | LEVEL (LL, IAG's long haul low cost from Barcelona) direct from flylevel.com through the shared real Chrome (see _browser.py). Plain HTTP clients get an Akamai "crypto" challenge page on the flight pages (the fare calend... |
| `flydubai` | flydubai (FZ) direct from flydubai.com through the shared headless Chrome (see _browser.py). Its booking app (flights2.flydubai.com) sits behind Akamai Bot Manager: plain HTTP clients get "Access Denied" on the flight AP... |
| `kiwiweb` | Kiwi.com through the GraphQL backend its own website uses (api.skypicker.com/umbrella/v2/graphql, keyless, Chrome TLS impersonation). |
| `skyscanner` | Skyscanner month view price calendar (the grid behind "Whole month" on skyscanner.net), keyless with Chrome TLS impersonation. |
