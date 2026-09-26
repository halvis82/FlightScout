"use client";
import { watchHref } from "@/lib/watch-slug";
import useSWR, { mutate } from "swr";
import Link from "next/link";
import { Check, Eye } from "lucide-react";
import { fetcher } from "@/lib/client";
import { watchSignature } from "@/lib/signature";
import { toast } from "./stores";
import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { AirportInput, PlaceChips } from "./airport-input";
import { useApp } from "./app-context";
import { Dialog } from "./dialog";
import { Button, ErrorNote, Field, Input, Segmented, Select, Switch } from "./ui";
import { api } from "@/lib/client";
import { addDays, isoDate } from "@/lib/format";
import { CURRENCIES, type Trip } from "@/lib/types";
import { tripsToObservations } from "@/lib/watch-logic";
import { checkNote } from "@/lib/watch-logic";

export type WatchForm = {
  name: string;
  origins: string[];
  destinations: string[];
  trip_type: "oneway" | "roundtrip" | "multicity";
  legs?: { origins: string[]; destinations: string[]; date: string; before?: number; after?: number; arrive_by?: string | null }[] | null;
  depart_start: string;
  depart_end: string;
  nights_min: number | null;
  nights_max: number | null;
  cabin: string;
  adults: number;
  max_stops: number | null;
  currency: string;
  include_split: boolean;
  alert_below: number | null;
  alert_drop_pct: number | null;
  notes?: string | null;
};

export function defaultWatch(currency: string, p?: Partial<WatchForm>): WatchForm {
  const start = addDays(isoDate(new Date()), 30);
  return {
    name: "",
    origins: [],
    destinations: [],
    trip_type: "roundtrip",
    depart_start: start,
    depart_end: addDays(start, 14),
    nights_min: 5,
    nights_max: 10,
    cabin: "economy",
    adults: 1,
    max_stops: null,
    currency,
    include_split: false,
    alert_below: null,
    alert_drop_pct: 10,
    ...p,
  };
}

export function WatchDialog({
  open,
  onClose,
  initial,
  watchId,
  onSaved,
  seedTrips,
}: {
  open: boolean;
  onClose: () => void;
  initial: WatchForm;
  watchId?: number;
  onSaved?: (row: { id: number } & Record<string, unknown>) => void;
  seedTrips?: Trip[];
}) {
  return (
    <Dialog open={open} onClose={onClose} title={watchId ? "Edit watch" : "Watch a route"} wide>
      <WatchFormBody initial={initial} watchId={watchId} onClose={onClose} onSaved={onSaved} seedTrips={seedTrips} />
    </Dialog>
  );
}

function WatchFormBody({
  initial,
  watchId,
  onClose,
  onSaved,
  seedTrips,
}: {
  initial: WatchForm;
  watchId?: number;
  onClose: () => void;
  onSaved?: (row: { id: number } & Record<string, unknown>) => void;
  seedTrips?: Trip[];
}) {
  const router = useRouter();
  const [f, setF] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const set = (p: Partial<WatchForm>) => setF((x) => ({ ...x, ...p }));

  async function save() {
    setBusy(true);
    setErr(null);
    try {
      const body = { ...f, name: f.name || `${f.origins.join("/")} to ${f.destinations.join("/")}` };
      const row = watchId
        ? await api<{ id: number } & Record<string, unknown>>(`/watches/${watchId}`, { method: "PATCH", body })
        : await api<{ id: number } & Record<string, unknown>>("/watches", { body });
      await mutate("/watches");
      // Start the price history with the results the watch was created from.
      if (!watchId && seedTrips?.length) {
        const obs = tripsToObservations(seedTrips, body.destinations).filter(
          (o) => o.depart_date >= body.depart_start && o.depart_date <= body.depart_end,
        );
        if (obs.length) await api(`/watches/${row.id}/observations`, { body: obs }).catch(() => {});
      }
      onClose();
      if (onSaved) onSaved(row);
      else router.push(watchHref(row as never));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Name" className="sm:col-span-2">
          <Input value={f.name} onChange={(e) => set({ name: e.target.value })} placeholder={`${f.origins.join("/") || "From"} to ${f.destinations.join("/") || "To"}`} />
        </Field>
        {f.trip_type === "multicity" ? (
          <div className="rounded-lg bg-surface-2 p-3 text-sm sm:col-span-2">
            <div className="font-medium">Multi city</div>
            <div className="mt-1 text-muted">
              {(f.legs ?? []).map((l, i) => (
                <div key={i}>
                  {l.origins.join("/")} → {l.destinations.join("/")}, {l.date}
                  {l.after ? ` ±${l.after}` : ""}
                </div>
              ))}
            </div>
            <p className="mt-1 text-xs text-faint">To change the flights, search that trip and watch it again. Everything below can be changed here.</p>
          </div>
        ) : (
          <>
        <Field label="From">
          <AirportInput value={f.origins} onChange={(origins) => set({ origins })} />
          <PlaceChips onPick={(c) => set({ origins: [...new Set([...f.origins, ...c])] })} />
        </Field>
        <Field label="To">
          <AirportInput value={f.destinations} onChange={(destinations) => set({ destinations })} />
          <PlaceChips onPick={(c) => set({ destinations: [...new Set([...f.destinations, ...c])] })} />
        </Field>
        <div className="sm:col-span-2">
          <Segmented
            value={f.trip_type}
            onChange={(trip_type) => set({ trip_type })}
            options={[
              { value: "roundtrip", label: "Round trip" },
              { value: "oneway", label: "One way" },
            ]}
          />
        </div>
        <Field label="Depart between">
          <Input type="date" value={f.depart_start} onChange={(e) => set({ depart_start: e.target.value, depart_end: f.depart_end < e.target.value ? e.target.value : f.depart_end })} />
        </Field>
        <Field label="and">
          <Input type="date" value={f.depart_end} min={f.depart_start} onChange={(e) => set({ depart_end: e.target.value })} />
        </Field>
          </>
        )}
        {f.trip_type === "roundtrip" && (
          <>
            <Field label="Nights at destination, min">
              <Input type="number" min={0} value={f.nights_min ?? ""} onChange={(e) => set({ nights_min: e.target.value === "" ? null : Number(e.target.value) })} />
            </Field>
            <Field label="max">
              <Input type="number" min={0} value={f.nights_max ?? ""} onChange={(e) => set({ nights_max: e.target.value === "" ? null : Number(e.target.value) })} />
            </Field>
          </>
        )}
        <Field label="Cabin">
          <Select value={f.cabin} onChange={(e) => set({ cabin: e.target.value })}>
            <option value="economy">Economy</option>
            <option value="premium">Premium economy</option>
            <option value="business">Business</option>
            <option value="first">First</option>
          </Select>
        </Field>
        <div className="grid grid-cols-3 gap-2">
          <Field label="Adults">
            <Input type="number" min={1} max={9} value={f.adults} onChange={(e) => set({ adults: Number(e.target.value) })} />
          </Field>
          <Field label="Stops">
            <Select value={f.max_stops ?? ""} onChange={(e) => set({ max_stops: e.target.value === "" ? null : Number(e.target.value) })}>
              <option value="">Any</option>
              <option value="0">Nonstop</option>
              <option value="1">1 max</option>
              <option value="2">2 max</option>
            </Select>
          </Field>
          <Field label="Currency">
            <Select value={f.currency} onChange={(e) => set({ currency: e.target.value })}>
              {CURRENCIES.map((c) => (
                <option key={c}>{c}</option>
              ))}
            </Select>
          </Field>
        </div>
        <Field label={`Alert when below (${f.currency})`}>
          <Input type="number" min={0} value={f.alert_below ?? ""} onChange={(e) => set({ alert_below: e.target.value === "" ? null : Number(e.target.value) })} placeholder="Optional" />
        </Field>
        <Field label="Alert when price drops by (%)">
          <Input type="number" min={1} max={90} value={f.alert_drop_pct ?? ""} onChange={(e) => set({ alert_drop_pct: e.target.value === "" ? null : Number(e.target.value) })} placeholder="Optional" />
        </Field>
        <div className="sm:col-span-2">
          <Switch
            checked={f.include_split}
            onChange={(include_split) => set({ include_split })}
            label={<span>Also track split ticket and stopover routes <span className="text-muted">(slower, uses more searches)</span></span>}
          />
        </div>
      </div>
      {err && <div className="mt-3"><ErrorNote>{err}</ErrorNote></div>}
      <div className="mt-4 flex justify-end gap-2 border-t border-border pt-3">
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button variant="primary" onClick={save} loading={busy} disabled={!f.origins.length || !f.destinations.length}>
          {watchId ? "Save changes" : "Start watching"}
        </Button>
      </div>
    </>
  );
}

// Hook for opening the dialog from anywhere with a prefilled form.
const inflight = new Set<string>();

// "Watch this search" with a clear state: Watch, Saving..., Watching ✓ (links
// to the watch). Checks the watchlist, so it also says Watching after a reload.
export function WatchButton({ watch, seed, label = "Watch this search" }: { watch: Partial<WatchForm>; seed?: Trip[]; label?: string }) {
  const { currency } = useApp();
  const w = useWatchDialog();
  const { data: list } = useSWR<Array<Record<string, unknown>>>("/watches", fetcher, { revalidateOnFocus: false });
  const [busy, setBusy] = useState(false);
  const savedAt = useRef(0);
  const f = defaultWatch(currency, watch);
  const key = watchSignature({
    origins: f.origins,
    destinations: f.destinations,
    tripType: f.trip_type,
    departStart: f.depart_start,
    departEnd: f.depart_end,
    nightsMin: f.nights_min,
    nightsMax: f.nights_max,
    cabin: f.cabin,
    adults: f.adults,
    legs: f.legs ?? null,
  });
  const existing = (list ?? []).find(
    (x) =>
      watchSignature({
        origins: x.origins as string[],
        destinations: x.destinations as string[],
        tripType: x.tripType as string,
        departStart: x.departStart as string,
        departEnd: x.departEnd as string,
        nightsMin: x.nightsMin as number | null,
        nightsMax: x.nightsMax as number | null,
        cabin: x.cabin as string,
        adults: x.adults as number,
        legs: (x.legs as unknown) ?? null,
      }) === key,
  );
  if (existing)
    return (
      <Link
        href={watchHref(existing as never, list as never)}
        // the rest of a double or triple click that saved it must not navigate away
        onClick={(e) => {
          if (Date.now() - savedAt.current < 1500) e.preventDefault();
        }}
        title="On your watchlist. Open it."
        className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-good/40 bg-good-soft/40 px-3 text-sm font-medium text-good"
      >
        <Check className="size-3.5" /> Watching
      </Link>
    );
  return (
    <>
      <Button
        size="sm"
        disabled={busy}
        loading={busy}
        onClick={async () => {
          if (busy) return;
          savedAt.current = Date.now(); // the Watching link can appear before this returns
          setBusy(true);
          await w.open(watch, seed);
          savedAt.current = Date.now();
          setBusy(false);
        }}
      >
        {!busy && <Eye className="size-3.5" />} {busy ? "Saving" : label}
      </Button>
      {w.element}
    </>
  );
}

export function useWatchDialog() {
  const { currency, me } = useApp();
  const [state, setState] = useState<{ open: boolean; initial: WatchForm; seed?: Trip[] }>({ open: false, initial: defaultWatch(currency) });
  return {
    // One click: create the watch right away (sensible defaults), seed it
    // with the current results, and offer the full form from the toast.
    open: async (p?: Partial<WatchForm>, seed?: Trip[]): Promise<{ id: number } | null> => {
      const f = defaultWatch(currency, p);
      const body = { ...f, name: f.name || `${f.origins.join("/")} to ${f.destinations.join("/")}` };
      const sig = JSON.stringify(body);
      if (inflight.has(sig)) return null; // a double click while the first save is running
      inflight.add(sig);
      try {
        const row = await api<{ id: number; existing?: boolean }>("/watches", { body });
        if (!row.existing && seed?.length) {
          const obs = tripsToObservations(seed, body.destinations).filter(
            (o) => o.depart_date >= body.depart_start && o.depart_date <= body.depart_end,
          );
          if (obs.length) await api(`/watches/${row.id}/observations`, { body: obs }).catch(() => {});
        }
        await mutate("/watches");
        toast(
          {
            text: row.existing ? `Already watching ${body.name}.` : `Watching ${body.name}. ${checkNote(Boolean(me?.guest))}`,
            action: { label: "Open", href: watchHref(row as never) },
            tone: "good",
          },
          5000,
        );
        return row;
      } catch {
        // fall back to the form (e.g. missing fields)
        setState({ open: true, initial: f, seed });
        return null;
      } finally {
        inflight.delete(sig);
      }
    },
    edit: (p?: Partial<WatchForm>, seed?: Trip[]) => setState({ open: true, initial: defaultWatch(currency, p), seed }),
    element: (
      <WatchDialog
        open={state.open}
        initial={state.initial}
        seedTrips={state.seed}
        onClose={() => setState((s) => ({ ...s, open: false }))}
      />
    ),
  };
}
