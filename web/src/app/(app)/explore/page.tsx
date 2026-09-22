"use client";
import { useMemo, useState } from "react";
import Link from "next/link";
import { Compass, ExternalLink, Search } from "lucide-react";
import { AirportInput, PlaceChips } from "@/components/airport-input";
import { useApp } from "@/components/app-context";
import { RouteMap, type MapPoint } from "@/components/route-map";
import { Badge, Button, Card, Empty, ErrorNote, Field, Input, PageHeader, Segmented, Select, Spinner } from "@/components/ui";
import { api } from "@/lib/client";
import { addDays, dayDiff, formatDate, isoDate } from "@/lib/format";
import { airport, expandCodes, useAirports } from "@/lib/airports-client";
import { CURRENCIES, type Destination } from "@/lib/types";

type Sort = "price" | "distance" | "date";

function km(a: string, b: string) {
  const pa = airport(a);
  const pb = airport(b);
  if (!pa || !pb) return 0;
  const r = Math.PI / 180;
  const h = Math.sin(((pb.lat - pa.lat) * r) / 2) ** 2 + Math.cos(pa.lat * r) * Math.cos(pb.lat * r) * Math.sin(((pb.lon - pa.lon) * r) / 2) ** 2;
  return 12742 * Math.asin(Math.sqrt(h));
}

export default function ExplorePage() {
  const { settings, currency, money, convert, places } = useApp();
  useAirports();
  const [pickedOrigins, setOrigins] = useState<string[] | null>(null);
  const origins = useMemo(() => pickedOrigins ?? settings?.defaultOrigins.slice(0, 2) ?? [], [pickedOrigins, settings]);
  const [start, setStart] = useState(() => addDays(isoDate(new Date()), 14));
  const [end, setEnd] = useState(() => addDays(isoDate(new Date()), 60));
  const [trip, setTrip] = useState<"roundtrip" | "oneway">("roundtrip");
  const [nMin, setNMin] = useState(3);
  const [nMax, setNMax] = useState(10);
  const [pickedCur, setCur] = useState<string | null>(null);
  const cur = pickedCur ?? currency;
  const [maxPrice, setMaxPrice] = useState<string>("");
  const [sort, setSort] = useState<Sort>("price");
  const [items, setItems] = useState<Destination[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);


  const interested = useMemo(() => new Set(places.filter((p) => p.kind === "interested").flatMap((p) => p.codes)), [places]);

  async function run() {
    setBusy(true);
    setErr(null);
    setItems(null);
    try {
      const codes = expandCodes(origins).slice(0, 4);
      const res = await Promise.allSettled(
        codes.map((o) =>
          api<{ items: Destination[]; errors?: Record<string, string> }>("/explore", {
            body: {
              origin: o,
              start,
              end,
              currency: cur,
              nights_min: trip === "roundtrip" ? nMin : null,
              nights_max: trip === "roundtrip" ? nMax : null,
            },
          }),
        ),
      );
      const all = res.flatMap((r) => (r.status === "fulfilled" ? r.value.items : []));
      const failed = res.filter((r) => r.status === "rejected") as PromiseRejectedResult[];
      const sourceErrors = res.flatMap((r) => (r.status === "fulfilled" ? Object.entries(r.value.errors ?? {}).map(([k, v]) => `${k}: ${v}`) : []));
      const msgs = [...failed.map((f) => (f.reason as Error).message), ...sourceErrors];
      if (msgs.length) setErr([...new Set(msgs)].join(" · ").slice(0, 600));
      // keep the cheapest per destination
      const best = new Map<string, Destination>();
      for (const d of all) {
        const cur = best.get(d.destination);
        if (!cur || convert(d.price, d.currency, "USD") < convert(cur.price, cur.currency, "USD")) best.set(d.destination, d);
      }
      setItems([...best.values()]);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const list = useMemo(() => {
    if (!items) return [];
    const cap = maxPrice ? Number(maxPrice) : Infinity;
    return items
      .filter((d) => convert(d.price, d.currency) <= cap)
      .sort((a, b) =>
        sort === "price"
          ? convert(a.price, a.currency, "USD") - convert(b.price, b.currency, "USD")
          : sort === "distance"
            ? km(a.origin, a.destination) - km(b.origin, b.destination)
            : (a.departure ?? "").localeCompare(b.departure ?? ""),
      );
  }, [items, maxPrice, sort, convert]);

  const points = useMemo<MapPoint[]>(() => {
    const cheapest = list.slice(0, 5).map((d) => d.destination);
    const pts: MapPoint[] = list.map((d) => ({
      code: d.destination,
      lat: d.lat,
      lon: d.lon,
      label: `${d.destination} ${money(d.price, d.currency, { compact: true })}`,
      tone: cheapest.includes(d.destination) ? "best" : "price",
      title: `${d.city ?? d.destination} · ${money(d.price, d.currency)}`,
      onClick: () => {
        setSelected(d.destination);
        document.getElementById(`dest-${d.destination}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
      },
    }));
    for (const o of expandCodes(origins)) pts.push({ code: o, tone: "origin" });
    return pts;
  }, [list, origins, money]);

  return (
    <div>
      <PageHeader title="Explore" sub="Cheapest places to go from your airports in a date window. Sources: Kiwi.com anywhere search and Ryanair fare finder." />
      <Card className="mb-4 p-3 sm:p-4">
        <div className="grid grid-cols-1 gap-2 md:grid-cols-[1.4fr_150px_150px_auto]">
          <Field label="From">
            <AirportInput value={origins} onChange={setOrigins} placeholder="Your airports" />
            <PlaceChips kinds={["home", "frequent"]} onPick={(c) => setOrigins([...new Set([...origins, ...c])])} />
          </Field>
          <Field label="Leave after">
            <Input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
          </Field>
          <Field label="Leave before">
            <Input type="date" value={end} min={start} onChange={(e) => setEnd(e.target.value)} />
          </Field>
          <Field label="Currency">
            <Select value={cur} onChange={(e) => setCur(e.target.value)}>
              {CURRENCIES.map((c) => (
                <option key={c}>{c}</option>
              ))}
            </Select>
          </Field>
        </div>
        <div className="mt-3 flex flex-wrap items-end gap-3 border-t border-border pt-3">
          <Segmented
            size="sm"
            value={trip}
            onChange={setTrip}
            options={[
              { value: "roundtrip", label: "Round trip" },
              { value: "oneway", label: "One way" },
            ]}
          />
          {trip === "roundtrip" && (
            <div className="flex items-center gap-2 text-sm text-muted">
              <Input type="number" className="h-7 w-16" min={0} value={nMin} onChange={(e) => setNMin(Number(e.target.value))} /> to
              <Input type="number" className="h-7 w-16" min={nMin} value={nMax} onChange={(e) => setNMax(Number(e.target.value))} /> nights
            </div>
          )}
          <Button variant="primary" className="ml-auto" onClick={run} loading={busy} disabled={!origins.length}>
            <Compass className="size-4" /> Explore
          </Button>
        </div>
      </Card>
      {err && <div className="mb-3"><ErrorNote>{err}</ErrorNote></div>}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_420px]">
        <RouteMap points={points} className="h-72 lg:h-[560px]" fitKey={String(items?.length ?? 0) + origins.join()} />
        <div className="min-w-0">
          {busy && (
            <div className="flex items-center gap-2 text-sm text-muted">
              <Spinner /> Asking Kiwi.com and Ryanair for every destination
            </div>
          )}
          {!busy && !items && <Empty title="Where could you go?">Pick your airports and a window. The map fills with the cheapest destinations.</Empty>}
          {items && (
            <>
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <Segmented
                  size="sm"
                  value={sort}
                  onChange={setSort}
                  options={[
                    { value: "price", label: "Cheapest" },
                    { value: "distance", label: "Closest" },
                    { value: "date", label: "Soonest" },
                  ]}
                />
                <Input
                  className="h-7 w-32 text-xs"
                  type="number"
                  placeholder={`Max ${currency}`}
                  value={maxPrice}
                  onChange={(e) => setMaxPrice(e.target.value)}
                />
                <span className="text-xs text-muted">{list.length} destinations</span>
              </div>
              <div className="max-h-[520px] space-y-1 overflow-y-auto pr-1">
                {list.map((d) => {
                  const nights = d.departure && d.return_date ? dayDiff(d.departure, d.return_date) : null;
                  const q = new URLSearchParams({ from: d.origin, to: d.destination, d: d.departure ?? start, cur, tt: d.return_date ? "roundtrip" : "oneway" });
                  if (d.return_date) q.set("r", d.return_date);
                  return (
                    <div
                      key={d.destination}
                      id={`dest-${d.destination}`}
                      className={`flex items-center gap-3 rounded-md border px-3 py-2 ${selected === d.destination ? "border-accent bg-accent-soft/40" : "border-border bg-surface"}`}
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5 text-sm font-medium">
                          <span className="truncate">{d.city ?? airport(d.destination)?.city ?? d.destination}</span>
                          <span className="font-mono text-xs text-muted">{d.destination}</span>
                          {interested.has(d.destination) && <Badge tone="accent">On your list</Badge>}
                        </div>
                        <div className="text-xs text-muted">
                          from {d.origin} · {formatDate(d.departure)}
                          {nights != null && ` · ${nights} nights`} · {d.source}
                        </div>
                      </div>
                      <div className="text-right">
                        <div className="font-semibold tabular-nums">{money(d.price, d.currency)}</div>
                        <div className="flex justify-end gap-1.5 text-xs">
                          <Link href={`/?${q}`} className="inline-flex items-center gap-0.5 text-accent hover:underline">
                            <Search className="size-3" /> Compare
                          </Link>
                          {d.booking_url && (
                            <a href={d.booking_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-0.5 text-muted hover:text-fg">
                              Book <ExternalLink className="size-3" />
                            </a>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
