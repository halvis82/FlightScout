"use client";
import { useMemo, useState } from "react";
import Link from "next/link";
import { Compass, Home, Plane, Plus, Star, Trash2 } from "lucide-react";
import { AirportInput } from "@/components/airport-input";
import { useApp, type Place } from "@/components/app-context";
import { RouteMap, type MapPoint } from "@/components/route-map";
import { Badge, Button, Card, Empty, ErrorNote, Field, Input, PageHeader, Select } from "@/components/ui";
import { api } from "@/lib/client";
import { airport, useAirports } from "@/lib/airports-client";

const KINDS = {
  home: { label: "Homes", icon: Home, hint: "Where trips start. Used as default origins." },
  frequent: { label: "Fly often", icon: Plane, hint: "Regular destinations and alternates." },
  interested: { label: "Want to go", icon: Star, hint: "Places you're curious about. Highlighted in Explore." },
} as const;

export default function PlacesPage() {
  const { places, refreshPlaces, settings, refreshMe } = useApp();
  useAirports();
  const [label, setLabel] = useState("");
  const [codes, setCodes] = useState<string[]>([]);
  const [kind, setKind] = useState<Place["kind"]>("frequent");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function add() {
    setBusy(true);
    setErr(null);
    try {
      await api("/places", { body: { label: label || codes.join("/"), codes, kind } });
      if (kind === "home" && settings) {
        await api("/settings", { method: "PATCH", body: { defaultOrigins: [...new Set([...settings.defaultOrigins, ...codes])] } });
        refreshMe();
      }
      setLabel("");
      setCodes([]);
      refreshPlaces();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function remove(p: Place) {
    await api(`/places/${p.id}`, { method: "DELETE" });
    if (p.kind === "home" && settings) {
      await api("/settings", { method: "PATCH", body: { defaultOrigins: settings.defaultOrigins.filter((c) => !p.codes.includes(c)) } });
      refreshMe();
    }
    refreshPlaces();
  }

  const points = useMemo<MapPoint[]>(
    () =>
      places.flatMap((p) =>
        p.codes.map((c) => ({ code: c, label: c, tone: p.kind === "home" ? ("origin" as const) : p.kind === "interested" ? ("best" as const) : ("dest" as const), title: `${p.label} · ${airport(c)?.name ?? c}` })),
      ),
    [places],
  );

  return (
    <div>
      <PageHeader title="Places" sub="Your homes, regular destinations and wish list. They show up as one click picks in every search." />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_420px]">
        <div className="space-y-4">
          <Card className="p-3">
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-[1fr_1.4fr_140px_auto] sm:items-end">
              <Field label="Label">
                <Input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. Home, Mom's, Bay Area" />
              </Field>
              <Field label="Airports">
                <AirportInput value={codes} onChange={setCodes} placeholder="One or more airports" />
              </Field>
              <Field label="Type">
                <Select value={kind} onChange={(e) => setKind(e.target.value as Place["kind"])}>
                  <option value="home">Home</option>
                  <option value="frequent">Fly often</option>
                  <option value="interested">Want to go</option>
                </Select>
              </Field>
              <Button variant="primary" onClick={add} loading={busy} disabled={!codes.length}>
                <Plus className="size-4" /> Add
              </Button>
            </div>
            {err && <div className="mt-2"><ErrorNote>{err}</ErrorNote></div>}
          </Card>
          {!places.length && <Empty title="No places yet">Add your home airports first. Group nearby airports under one label, like SFO, OAK and SJC as &quot;Bay Area&quot;.</Empty>}
          {(Object.keys(KINDS) as Place["kind"][]).map((k) => {
            const list = places.filter((p) => p.kind === k);
            if (!list.length) return null;
            const K = KINDS[k];
            return (
              <div key={k}>
                <div className="mb-1.5 flex items-center gap-1.5 text-sm font-semibold">
                  <K.icon className="size-4 text-muted" /> {K.label}
                  <span className="font-normal text-xs text-muted">{K.hint}</span>
                </div>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {list.map((p) => (
                    <Card key={p.id} className="flex items-center gap-3 px-3 py-2">
                      <div className="min-w-0 flex-1">
                        <div className="font-medium">{p.label}</div>
                        <div className="flex flex-wrap gap-1 pt-0.5">
                          {p.codes.map((c) => (
                            <Badge key={c} tone="accent" title={airport(c)?.name}>
                              {c}
                            </Badge>
                          ))}
                        </div>
                      </div>
                      <Link href={`/explore`} className="rounded p-1.5 text-muted hover:bg-surface-2 hover:text-fg" title="Explore from here" onClick={() => {}}>
                        <Compass className="size-4" />
                      </Link>
                      <button onClick={() => remove(p)} className="rounded p-1.5 text-muted hover:bg-bad-soft hover:text-bad" aria-label={`Remove ${p.label}`}>
                        <Trash2 className="size-4" />
                      </button>
                    </Card>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
        <RouteMap points={points} className="h-72 lg:h-[480px]" fitKey={String(places.length)} />
      </div>
    </div>
  );
}
