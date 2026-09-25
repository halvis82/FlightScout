// Runs inside Google Flights, but only when FlightScout Helper loaded the
// page in its own hidden frame (never on pages you open yourself). It hands
// the flight list Google's own JavaScript fetches (GetShoppingResults) to
// the extension, so FlightScout sees exactly what you would see on Google.
(() => {
  const anc = location.ancestorOrigins;
  if (window.top === window || !anc || !anc.length || !anc[anc.length - 1].startsWith("chrome-extension://")) return;
  const send = (body) => window.parent.postMessage({ source: "flightscout-google", type: "list", body }, "*");
  const open = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    if (String(url).includes("GetShoppingResults")) {
      this.addEventListener("loadend", () => {
        if (this.status === 200) send(this.responseText);
      });
    }
    return open.call(this, method, url, ...rest);
  };
  const f = window.fetch;
  window.fetch = async (...args) => {
    const res = await f(...args);
    try {
      const u = typeof args[0] === "string" ? args[0] : args[0]?.url;
      if (u && u.includes("GetShoppingResults") && res.ok) res.clone().text().then(send);
    } catch {}
    return res;
  };
})();
