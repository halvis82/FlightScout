// Hidden page that loads Google Flights in a frame (with your Google session)
// and waits for the flight list google-hook.js hands over.

// GetShoppingResults answers in "wrb.fr" chunks; the flight rows sit in each
// chunk's inner [2][0] (top flights) and [3][0] (other flights).
function rowsFrom(body) {
  const rows = [];
  for (const line of body.split("\n")) {
    if (!line.startsWith('[["wrb.fr"')) continue;
    try {
      for (const e of JSON.parse(line)) {
        if (e[0] !== "wrb.fr" || typeof e[2] !== "string") continue;
        const inner = JSON.parse(e[2]);
        for (const i of [2, 3]) if (Array.isArray(inner?.[i]?.[0])) rows.push(...inner[i][0]);
      }
    } catch {}
  }
  return rows;
}

function capture(url, timeoutMs = 25000) {
  return new Promise((resolve) => {
    const frame = document.createElement("iframe");
    let rows = [];
    let settle = null;
    const done = () => {
      window.removeEventListener("message", on);
      clearTimeout(timer);
      frame.remove();
      resolve(rows);
    };
    const on = (e) => {
      if (e.origin !== "https://www.google.com" || e.source !== frame.contentWindow) return;
      if (e.data?.source !== "flightscout-google" || e.data.type !== "list") return;
      rows = rows.concat(rowsFrom(e.data.body));
      // the list sometimes comes in two answers: wait a moment for a second
      clearTimeout(settle);
      settle = setTimeout(done, 1500);
    };
    const timer = setTimeout(done, timeoutMs);
    window.addEventListener("message", on);
    frame.src = url;
    document.body.appendChild(frame);
  });
}

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (msg?.target !== "offscreen" || msg.type !== "captureList") return;
  capture(msg.url).then((rows) => reply({ rows }));
  return true;
});
