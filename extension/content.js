// Bridge between a FlightScout page and the extension. The page talks to it
// with window.postMessage; only messages from the page itself are accepted.
const VERSION = chrome.runtime.getManifest().version;
const hello = () => window.postMessage({ source: "flightscout-ext", type: "hello", version: VERSION }, window.location.origin);

window.addEventListener("message", (e) => {
  if (e.source !== window || e.origin !== window.location.origin) return;
  const m = e.data;
  if (!m || m.source !== "flightscout-page") return;
  if (m.type === "ping") return hello();
  if (m.type === "fetchPages") {
    chrome.runtime.sendMessage({ type: "fetchPages", urls: m.urls }, (res) => {
      window.postMessage({ source: "flightscout-ext", type: "pages", id: m.id, pages: res?.pages ?? {} }, window.location.origin);
    });
  }
});
hello();
document.addEventListener("DOMContentLoaded", hello);
