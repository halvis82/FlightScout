"use client";
// While a FlightScout tab is open, tell the processes that only run on demand
// that it's still in use: the local website (flightscout local, when this page
// is served from localhost) and the local runner (when searches use it). Close
// the tab and both stop a couple of minutes later.
import { useEffect } from "react";
import { LOCAL_RUNNER_URL, localRunnerActive } from "@/lib/local-runner";

export function KeepAlive() {
  useEffect(() => {
    const local = ["localhost", "127.0.0.1"].includes(window.location.hostname);
    const ping = () => {
      if (local) fetch("/api/v1/alive", { cache: "no-store" }).catch(() => {});
    };
    const pingRunner = () => {
      if (localRunnerActive()) fetch(`${LOCAL_RUNNER_URL}/alive`, { cache: "no-store", mode: "cors" }).catch(() => {});
    };
    const a = setInterval(ping, 30_000);
    const b = setInterval(pingRunner, 60_000);
    return () => {
      clearInterval(a);
      clearInterval(b);
    };
  }, []);
  return null;
}
