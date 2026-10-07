"use client";

import { useEffect } from "react";

const PING_MS = 30_000;

export function KeepAlive() {
  useEffect(() => {
    if (!["localhost", "127.0.0.1"].includes(window.location.hostname)) return;

    const ping = () => {
      if (document.visibilityState !== "visible") return;
      void fetch("/api/v1/alive", { cache: "no-store" }).catch(() => {});
    };

    ping();
    const timer = window.setInterval(ping, PING_MS);
    document.addEventListener("visibilitychange", ping);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", ping);
    };
  }, []);

  return null;
}
