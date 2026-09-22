"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Plus, Trash2 } from "lucide-react";
import { AirportInput } from "@/components/airport-input";
import { useApp } from "@/components/app-context";
import { Button, Card, ErrorNote, Field, Input, Select } from "@/components/ui";
import { api } from "@/lib/client";
import { CURRENCIES } from "@/lib/types";

type Row = { label: string; codes: string[]; kind: "home" | "frequent" | "interested" };

export default function Onboarding() {
  const router = useRouter();
  const { refreshMe, refreshPlaces, places } = useApp();
  const [currency, setCurrency] = useState("USD");
  const [rows, setRows] = useState<Row[]>([{ label: "", codes: [], kind: "home" }]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const update = (i: number, p: Partial<Row>) => setRows((r) => r.map((x, j) => (j === i ? { ...x, ...p } : x)));

  async function finish(skip = false) {
    setBusy(true);
    setErr(null);
    try {
      if (!skip) {
        for (const r of rows.filter((r) => r.codes.length)) {
          await api("/places", { body: { ...r, label: r.label || r.codes.join("/") } });
        }
      }
      const homes = rows.filter((r) => r.kind === "home").flatMap((r) => r.codes);
      await api("/settings", { method: "PATCH", body: { currency, onboarded: true, defaultOrigins: skip ? [] : homes } });
      await Promise.all([refreshMe(), refreshPlaces()]);
      router.replace("/");
    } catch (e) {
      setErr((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="text-2xl font-semibold tracking-tight">Welcome to FlightScout</h1>
      <p className="mt-1 text-sm text-muted">
        Tell FlightScout where you usually fly from and to. Places become one click picks in every search, and your homes are the
        default origin. You can change all of this later.
      </p>
      <Card className="mt-6 space-y-5 p-5">
        <Field label="Display currency" hint="Prices from every source are converted to this using ECB rates.">
          <Select value={currency} onChange={(e) => setCurrency(e.target.value)} className="w-40">
            {CURRENCIES.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </Select>
        </Field>
        <div className="space-y-3">
          <div className="text-[11px] font-medium uppercase tracking-wide text-muted">Your places</div>
          {places.length > 0 && <p className="text-sm text-muted">You already have {places.length} saved places.</p>}
          {rows.map((r, i) => (
            <div key={i} className="grid grid-cols-1 gap-2 sm:grid-cols-[1fr_1.4fr_auto_auto]">
              <Input placeholder="Label, e.g. Home" value={r.label} onChange={(e) => update(i, { label: e.target.value })} />
              <AirportInput value={r.codes} onChange={(codes) => update(i, { codes })} placeholder="Airports, e.g. SAN or NYC" />
              <Select value={r.kind} onChange={(e) => update(i, { kind: e.target.value as Row["kind"] })}>
                <option value="home">Home</option>
                <option value="frequent">Fly often</option>
                <option value="interested">Want to go</option>
              </Select>
              <Button variant="ghost" onClick={() => setRows((x) => x.filter((_, j) => j !== i))} aria-label="Remove">
                <Trash2 className="size-4" />
              </Button>
            </div>
          ))}
          <Button size="sm" onClick={() => setRows((r) => [...r, { label: "", codes: [], kind: "frequent" }])}>
            <Plus className="size-3.5" /> Add place
          </Button>
        </div>
        {err && <ErrorNote>{err}</ErrorNote>}
        <div className="flex justify-between border-t border-border pt-4">
          <Button variant="ghost" onClick={() => finish(true)} disabled={busy}>
            Skip for now
          </Button>
          <Button variant="primary" onClick={() => finish()} loading={busy}>
            Save and start searching
          </Button>
        </div>
      </Card>
    </div>
  );
}
