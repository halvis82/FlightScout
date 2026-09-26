# FlightScout Helper (browser extension)

Makes FlightScout's Google Flights searches run from your own browser and IP instead of the shared server.

How it works: the FlightScout page asks the extension for specific `google.com/travel/flights` pages; the extension
fetches them (with your normal Google cookies), extracts only the flight data blob (`ds:1`) and hands it back. The
FlightScout server parses it with the same code it uses for its own searches (`engine/src/flightscout/browser_fetch.py`).
A one way search is one round, a round trip two (outbound list, then the return pages in parallel). Price calendars
work the same way.

Since 1.1: the full priced flight list (what Google's Cheapest tab shows) is only fetched by the page's own JavaScript,
so for `list:<url>` requests the extension loads the page in a hidden offscreen frame (`offscreen.js`) with your
Google session and `google-hook.js` hands over that `GetShoppingResults` answer. The hook does nothing on Google pages
you open yourself (it only runs inside a frame whose parent is this extension). A session rule lets only this
extension's own frames load Google Flights (it drops `X-Frame-Options` and presents the load as a normal page load).

Permissions: `https://www.google.com/*`, `offscreen` and `declarativeNetRequestWithHostAccess` (for the rule above), and it only answers FlightScout pages (flightscout-app.vercel.app and
localhost:3000). It only fetches Google Flights URLs. Running your own copy on another address? Add it to
`content_scripts[0].matches` in `manifest.json` before loading the folder.

Install (Chrome, Edge, Brave, Arc): download `flightscout-helper.zip` from the site's Settings page (or use this
folder), unzip, open `chrome://extensions`, enable Developer mode, Load unpacked, pick the folder.

After changing files here, rebuild the download: `cd extension && rm -f ../web/public/flightscout-helper.zip && zip -qr ../web/public/flightscout-helper.zip . -x "*.DS_Store"`.
