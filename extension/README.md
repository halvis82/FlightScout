# FlightScout Helper (browser extension)

Makes FlightScout's Google Flights searches run from your own browser and IP instead of the shared server.

How it works: the FlightScout page asks the extension for specific `google.com/travel/flights` pages; the extension
fetches them (with your normal Google cookies), extracts only the flight data blob (`ds:1`) and hands it back. The
FlightScout server parses it with the same code it uses for its own searches (`engine/src/flightscout/browser_fetch.py`).
A one way search is one round, a round trip two (outbound list, then the return pages in parallel). Price calendars
work the same way.

Permissions: `https://www.google.com/*` only, and it only answers FlightScout pages (flightscout-app.vercel.app,
any *.vercel.app deployment, localhost:3000). It only fetches Google Flights URLs.

Install (Chrome, Edge, Brave, Arc): download `flightscout-helper.zip` from the site's Settings page (or use this
folder), unzip, open `chrome://extensions`, enable Developer mode, Load unpacked, pick the folder.

After changing files here, rebuild the download: `cd extension && zip -qr ../web/public/flightscout-helper.zip manifest.json background.js content.js icon128.png`.
