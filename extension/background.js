// FlightScout Helper: fetches Google Flights pages from this browser (your own
// IP and Google cookies) and returns just the flight data ("ds:1") to the
// FlightScout page that asked. Only google.com/travel/flights URLs are allowed.

const ALLOWED = /^https:\/\/www\.google\.com\/travel\/flights(\/booking)?\?/;
const CONCURRENCY = 4;

function extract(html) {
  const blobs = html.matchAll(/AF_initDataCallback\((\{[\s\S]*?\})\);/g);
  for (const m of blobs) {
    const blob = m[1];
    const key = /key:\s*'([^']+)'/.exec(blob);
    if (!key || key[1] !== "ds:1") continue;
    const data = /data:([\s\S]*?), sideChannel/.exec(blob);
    if (!data) continue;
    try {
      // The parser only reads the first sections (session and flight rows);
      // dropping the rest keeps uploads small.
      const parsed = JSON.parse(data[1]);
      return Array.isArray(parsed) ? parsed.slice(0, 8) : parsed;
    } catch {
      return null;
    }
  }
  return null;
}

async function fetchOne(url) {
  if (!ALLOWED.test(url)) return [url, null];
  try {
    const res = await fetch(url, { credentials: "include", headers: { "Accept-Language": "en-US,en;q=0.9" } });
    if (!res.ok) return [url, null];
    return [url, extract(await res.text())];
  } catch {
    return [url, null];
  }
}

async function fetchAll(urls) {
  const out = {};
  const queue = [...new Set(urls)].slice(0, 40);
  async function worker() {
    while (queue.length) {
      const [u, data] = await fetchOne(queue.shift());
      if (data) out[u] = data;
    }
  }
  await Promise.all(Array.from({ length: CONCURRENCY }, worker));
  return out;
}

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (msg?.type === "fetchPages" && Array.isArray(msg.urls)) {
    fetchAll(msg.urls).then((pages) => reply({ pages }));
    return true; // async reply
  }
  if (msg?.type === "ping") reply({ ok: true, version: chrome.runtime.getManifest().version });
});
