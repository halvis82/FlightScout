"use client";
import { useState } from "react";
import Link from "next/link";
import { Button, ErrorNote } from "@/components/ui";

export function Unsubscribe({ u, s, email }: { u: string; s: string; email: string }) {
  const [state, setState] = useState<"ask" | "off" | "on">("ask");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function set(on: boolean) {
    setBusy(true);
    setErr(null);
    try {
      const r = await fetch(`/api/v1/unsubscribe?u=${encodeURIComponent(u)}&s=${encodeURIComponent(s)}${on ? "&undo=1" : ""}`, { method: "POST" });
      if (!r.ok) throw new Error();
      setState(on ? "on" : "off");
    } catch {
      setErr("Something went wrong. Please try again.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <h1 className="text-lg font-semibold">
        {state === "ask" ? "Stop price alert emails?" : state === "off" ? "You're unsubscribed" : "Price emails are back on"}
      </h1>
      <p className="mt-2 text-sm text-muted">
        {state === "ask"
          ? `We'll stop emailing ${email} about price changes. Your watchlist keeps tracking prices, and alerts still show in FlightScout.`
          : state === "off"
            ? `${email} won't get price alert emails anymore. Changed your mind? You can turn them back on.`
            : `We'll email ${email} again when a watched flight gets cheaper.`}
      </p>
      <div className="mt-4 flex flex-col items-center gap-2">
        {state === "ask" && <Button variant="primary" disabled={busy} onClick={() => set(false)}>Unsubscribe</Button>}
        {state === "off" && <Button variant="soft" disabled={busy} onClick={() => set(true)}>Turn price emails back on</Button>}
        <Link href="/" className="text-sm text-accent hover:underline">Go to FlightScout</Link>
      </div>
      {err && <div className="mt-3"><ErrorNote>{err}</ErrorNote></div>}
    </>
  );
}
