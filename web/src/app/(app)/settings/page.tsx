"use client";
import { useState } from "react";
import useSWR from "swr";
import { Check, Copy, Fingerprint, KeyRound, Plus, Trash2 } from "lucide-react";
import { AirportInput } from "@/components/airport-input";
import { useApp } from "@/components/app-context";
import { cityOf } from "@/lib/airports-client";
import { PlainButton, Badge, Button, Card, ErrorNote, Field, Input, PageHeader, Select, Switch } from "@/components/ui";
import { api, fetcher } from "@/lib/client";
import { authClient } from "@/lib/auth-client";
import { relativeTime } from "@/lib/format";
import { SELLER_PRESETS } from "@/lib/sellers";
import { CURRENCIES } from "@/lib/types";
import type { PlannerDefaults, SellerRule } from "@/lib/db/schema";

function Section({ title, sub, children }: { title: string; sub?: string; children: React.ReactNode }) {
  return (
    <Card className="p-4">
      <h2 className="font-semibold">{title}</h2>
      {sub && <p className="mb-3 text-sm text-muted">{sub}</p>}
      <div className={sub ? "" : "mt-3"}>{children}</div>
    </Card>
  );
}

export default function SettingsPage() {
  const { me, settings, refreshMe, places } = useApp();
  const [saved, setSaved] = useState(false);

  async function patch(body: Record<string, unknown>) {
    await api("/settings", { method: "PATCH", body });
    await refreshMe();
    setSaved(true);
    setTimeout(() => setSaved(false), 1500);
  }

  if (!settings || !me) return null;

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <PageHeader title="Settings" sub={me.user ? `Signed in as ${me.user.email}` : "Guest settings are saved in this browser."} actions={saved && <Badge tone="good"><Check className="size-3" /> Saved</Badge>} />
      <Section title="Display" sub="All prices are converted to this currency with daily ECB reference rates.">
        <Field label="Start searches from" className="mb-3 w-72">
          <Select
            value={settings.defaultOrigins.join(",")}
            onChange={(e) => patch({ defaultOrigins: e.target.value ? e.target.value.split(",") : [] })}
          >
            <option value="">Where I last searched from</option>
            {places.map((p) => (
              <option key={p.id} value={p.codes.join(",")}>
                {p.label} ({p.codes.join(", ")})
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Currency" className="w-40">
          <Select value={settings.currency} onChange={(e) => patch({ currency: e.target.value })}>
            {CURRENCIES.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </Select>
        </Field>
      </Section>
      <FavoritesSection />
      <PlannerSection key={JSON.stringify(settings.planner)} planner={settings.planner} onSave={(planner) => patch({ planner })} />
      <SellerSection rules={settings.sellerRules} onSave={(sellerRules) => patch({ sellerRules })} />
      {me.user ? (
        <>
          <AlertsSection />
          <PasskeySection />
          <TokensSection />
        </>
      ) : (
        <Section title="Account features" sub="Sign in to unlock these. Your guest data can be imported when you do.">
          <ul className="list-inside list-disc space-y-1 text-sm text-muted">
            <li>Daily background price tracking for every watch</li>
            <li>Email and push alerts when prices drop</li>
            <li>Sync across devices</li>
            <li>API tokens for the flightscout CLI, the MCP server and AI agents</li>
            <li>Passkey sign in</li>
          </ul>
          <a href="/login" className="mt-3 inline-flex h-9 items-center rounded-md bg-accent px-3 text-sm font-medium text-accent-fg">
            Sign in
          </a>
        </Section>
      )}
    </div>
  );
}

function FavoritesSection() {
  const { places, refreshPlaces } = useApp();
  const [adding, setAdding] = useState<string[]>([]);
  async function add(codes: string[]) {
    for (const c of codes) {
      if (places.some((p) => p.codes.includes(c))) continue;
      await api("/places", { body: { label: cityOf(c) ?? c, codes: [c], kind: places.length ? "frequent" : "home" } });
    }
    setAdding([]);
    refreshPlaces();
  }
  return (
    <div id="places">
      <Section
        title="Favorite airports and cities"
        sub="These show up as one click chips in From and To, and your homes prefill the search. Star any airport anywhere in the app to add it."
      >
        <div className="space-y-1.5">
          {places.map((p) => (
            <div key={p.id} className="flex items-center gap-2 rounded-lg border border-border px-3 py-2">
              <div className="min-w-0 flex-1">
                <span className="font-medium">{p.label}</span>{" "}
                <span className="font-mono text-xs text-muted">{p.codes.join(", ")}</span>
              </div>
              <Select
                className="h-7 w-32 text-xs"
                value={p.kind}
                onChange={async (e) => {
                  await api(`/places/${p.id}`, { method: "PATCH", body: { kind: e.target.value } });
                  refreshPlaces();
                }}
              >
                <option value="home">Home</option>
                <option value="frequent">Favorite</option>
                <option value="interested">Want to go</option>
              </Select>
              <Button
                size="sm"
                variant="ghost"
                aria-label={`Remove ${p.label}`}
                onClick={async () => {
                  await api(`/places/${p.id}`, { method: "DELETE" });
                  refreshPlaces();
                }}
              >
                <Trash2 className="size-3.5" />
              </Button>
            </div>
          ))}
          {!places.length && <p className="text-sm text-muted">No favorites yet. Add your home airports first.</p>}
          <div className="flex items-center gap-2 pt-1">
            <div className="flex-1">
              <AirportInput value={adding} onChange={setAdding} placeholder="Add an airport or city" />
            </div>
            <Button onClick={() => add(adding)} disabled={!adding.length}>
              <Plus className="size-3.5" /> Add
            </Button>
          </div>
        </div>
      </Section>
    </div>
  );
}

function PlannerSection({ planner, onSave }: { planner: PlannerDefaults; onSave: (p: PlannerDefaults) => void }) {
  const [p, setP] = useState(planner);
  const num = (k: keyof PlannerDefaults) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setP({ ...p, [k]: e.target.value === "" ? null : Number(e.target.value) });
  return (
    <Section title="Smart routes" sub="Limits for split tickets, stopovers and nested round trips. These are what you're willing to accept.">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Field label="Max stopover (days)">
          <Input type="number" min={0} max={30} value={p.max_stopover_days} onChange={num("max_stopover_days")} />
        </Field>
        <Field label="Min self transfer (hours)" hint="Buffer between separate tickets">
          <Input type="number" min={1} max={24} step={0.5} value={p.min_connection_hours} onChange={num("min_connection_hours")} />
        </Field>
        <Field label="Max total trip (days)" hint="Blank means no limit">
          <Input type="number" min={1} value={p.max_trip_days ?? ""} onChange={num("max_trip_days")} />
        </Field>
        <Field label="Hubs to try" hint="More finds more, but is slower">
          <Input type="number" min={1} max={30} value={p.max_hubs} onChange={num("max_hubs")} />
        </Field>
      </div>
      <div className="mt-3 flex flex-wrap gap-4">
        <Switch checked={p.allow_self_transfer} onChange={(v) => setP({ ...p, allow_self_transfer: v })} label="Allow self transfers" />
        <Switch checked={p.include_nested_roundtrips} onChange={(v) => setP({ ...p, include_nested_roundtrips: v })} label="Nested round trips (e.g. OSL⇄JFK + JFK⇄SAN)" />
      </div>
      <div className="mt-3 flex justify-end">
        <Button variant="primary" size="sm" onClick={() => onSave(p)}>
          Save
        </Button>
      </div>
    </Section>
  );
}

function SellerSection({ rules, onSave }: { rules: SellerRule[]; onSave: (r: SellerRule[]) => void }) {
  const [name, setName] = useState("");
  const [mode, setMode] = useState<"warn" | "block">("warn");
  const has = (r: SellerRule) => rules.some((x) => x.seller.toLowerCase() === r.seller.toLowerCase() && x.mode === r.mode);
  const add = (r: SellerRule) => onSave([...rules.filter((x) => x.seller.toLowerCase() !== r.seller.toLowerCase()), r]);
  return (
    <Section
      title="Sellers and travel agencies"
      sub="Block sellers to hide their results, or flag them with a warning. Self transfers, separate tickets and agency sold tickets are always labeled."
    >
      <div className="space-y-1.5">
        {rules.map((r) => (
          <div key={r.seller + r.mode} className="flex items-center gap-2 rounded-md border border-border px-3 py-1.5 text-sm">
            <span className="font-medium">{r.seller}</span>
            <Badge tone={r.mode === "block" ? "bad" : "warn"}>{r.mode === "block" ? "Hidden" : "Warning"}</Badge>
            {r.note && <span className="truncate text-xs text-muted">{r.note}</span>}
            <button className="ml-auto rounded p-1 text-muted hover:text-bad" onClick={() => onSave(rules.filter((x) => x !== r))} aria-label="Remove">
              <Trash2 className="size-3.5" />
            </button>
          </div>
        ))}
        {!rules.length && <p className="text-sm text-muted">No rules yet.</p>}
      </div>
      <div className="mt-3 flex flex-wrap items-end gap-2">
        <Field label="Seller name" className="flex-1">
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Gotogate" />
        </Field>
        <Select value={mode} onChange={(e) => setMode(e.target.value as "warn" | "block")}>
          <option value="warn">Warn</option>
          <option value="block">Hide</option>
        </Select>
        <Button
          disabled={!name.trim()}
          onClick={() => {
            add({ seller: name.trim(), mode });
            setName("");
          }}
        >
          <Plus className="size-4" /> Add rule
        </Button>
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5">
        <span className="text-xs text-muted">Presets:</span>
        {SELLER_PRESETS.filter((r) => !has(r)).map((r) => (
          <button key={r.seller + r.mode} title={r.note} onClick={() => add(r)} className="rounded-full border border-border px-2 py-0.5 text-xs text-muted hover:border-accent hover:text-accent">
            {r.mode === "block" ? "Hide" : "Warn"} {r.seller}
          </button>
        ))}
      </div>
    </Section>
  );
}

function urlB64ToUint8Array(base64: string) {
  const padding = "=".repeat((4 - (base64.length % 4)) % 4);
  const b = (base64 + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(b);
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
}

function AlertsSection() {
  const { me, settings, refreshMe, places } = useApp();
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  if (!me?.user || !settings) return null;
  const email = me.user.email;

  async function enablePush(on: boolean) {
    setErr(null);
    try {
      if (on) {
        if (!("serviceWorker" in navigator) || !("PushManager" in window)) throw new Error("This browser doesn't support web push.");
        const perm = await Notification.requestPermission();
        if (perm !== "granted") throw new Error("Notification permission was not granted.");
        const reg = await navigator.serviceWorker.register("/sw.js");
        await navigator.serviceWorker.ready;
        const sub =
          (await reg.pushManager.getSubscription()) ??
          (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlB64ToUint8Array(process.env.NEXT_PUBLIC_VAPID_PUBLIC_KEY!) }));
        await api("/push", { body: { subscription: sub.toJSON() } });
      } else {
        const reg = await navigator.serviceWorker.getRegistration();
        const sub = await reg?.pushManager.getSubscription();
        if (sub) {
          await api("/push", { method: "DELETE", body: { endpoint: sub.endpoint } });
          await sub.unsubscribe();
        }
      }
      await api("/settings", { method: "PATCH", body: { pushAlerts: on } });
      refreshMe();
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  return (
    <Section title="Alerts" sub="Alerts fire when a watch drops below its target price or falls by its drop percentage. They always appear under the bell.">
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <Switch
            checked={settings.emailAlerts}
            disabled={!me.features.email}
            onChange={async (v) => {
              await api("/settings", { method: "PATCH", body: { emailAlerts: v } });
              refreshMe();
            }}
            label={`Email to ${email}`}
          />
          {!me.features.email && <span className="text-xs text-faint">Needs RESEND_API_KEY and ALERT_FROM_EMAIL on the server.</span>}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Switch checked={settings.pushAlerts} disabled={!me.features.push} onChange={enablePush} label="Push notifications on this device" />
          {!me.features.push && <span className="text-xs text-faint">Needs VAPID keys on the server.</span>}
          {settings.pushAlerts && (
            <Button
              size="sm"
              onClick={async () => {
                const r = await api<{ sent: number }>("/push", { body: { test: true } });
                setMsg(r.sent ? `Sent to ${r.sent} device${r.sent > 1 ? "s" : ""}.` : "No subscribed devices.");
              }}
            >
              Send test
            </Button>
          )}
          {msg && <span className="text-xs text-muted">{msg}</span>}
        </div>
        {err && <ErrorNote>{err}</ErrorNote>}
      </div>
    </Section>
  );
}

type PasskeyRow = { id: string; name?: string | null; createdAt?: string | Date | null };

function PasskeySection() {
  const { data, mutate } = useSWR<PasskeyRow[]>("passkeys", async () => {
    const r = await authClient.passkey.listUserPasskeys();
    return (r.data ?? []) as unknown as PasskeyRow[];
  });
  const [err, setErr] = useState<string | null>(null);
  return (
    <Section title="Passkeys" sub="Sign in with Face ID, Touch ID or a security key instead of a password.">
      <div className="space-y-1.5">
        {data?.map((p) => (
          <div key={p.id} className="flex items-center gap-2 rounded-md border border-border px-3 py-1.5 text-sm">
            <Fingerprint className="size-4 text-muted" />
            {p.name || "Passkey"}
            <span className="text-xs text-faint">{p.createdAt ? `added ${relativeTime(p.createdAt)}` : ""}</span>
            <PlainButton
              className="ml-auto rounded p-1 text-muted hover:text-bad"
              aria-label="Remove passkey"
              onClick={async () => {
                await authClient.passkey.deletePasskey({ id: p.id });
                mutate();
              }}
            >
              <Trash2 className="size-3.5" />
            </PlainButton>
          </div>
        ))}
      </div>
      <Button
        className="mt-3"
        onClick={async () => {
          setErr(null);
          const r = await authClient.passkey.addPasskey({ name: navigator.platform || "This device" });
          if (r?.error) setErr(r.error.message ?? "Could not add passkey");
          mutate();
        }}
      >
        <Plus className="size-4" /> Add a passkey
      </Button>
      {err && <div className="mt-2"><ErrorNote>{err}</ErrorNote></div>}
    </Section>
  );
}

type TokenRow = { id: number; name: string; prefix: string; created_at: string; last_used_at: string | null };

function TokensSection() {
  const { data, mutate } = useSWR<TokenRow[]>("/tokens", fetcher);
  const [name, setName] = useState("");
  const [fresh, setFresh] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  const cmd = fresh ? `flightscout login --url ${origin} --token ${fresh}` : "";
  return (
    <Section
      title="API tokens"
      sub="For the flightscout CLI, the MCP server and AI agents. Results they find are saved to your History and feed your watches."
    >
      <div className="flex gap-2">
        <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Token name, e.g. MacBook CLI" />
        <Button
          variant="primary"
          onClick={async () => {
            const r = await api<{ token: string }>("/tokens", { body: { name: name || "CLI" } });
            setFresh(r.token);
            setName("");
            mutate();
          }}
        >
          <KeyRound className="size-4" /> Create
        </Button>
      </div>
      {fresh && (
        <div className="mt-3 rounded-md border border-good/40 bg-good-soft p-3 text-sm">
          <div className="mb-1 font-medium text-good">Copy this now. It won&apos;t be shown again.</div>
          <div className="flex items-center gap-2">
            <code className="min-w-0 flex-1 overflow-x-auto rounded bg-surface px-2 py-1 font-mono text-xs whitespace-nowrap">{cmd}</code>
            <Button
              size="sm"
              onClick={() => {
                navigator.clipboard.writeText(cmd);
                setCopied(true);
                setTimeout(() => setCopied(false), 1500);
              }}
            >
              {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
            </Button>
          </div>
          <p className="mt-2 text-xs text-muted">
            Run that in a terminal after installing the CLI. For MCP clients set FLIGHTSCOUT_URL={origin} and FLIGHTSCOUT_TOKEN to the token.
          </p>
        </div>
      )}
      <div className="mt-3 space-y-1.5">
        {data?.map((t) => (
          <div key={t.id} className="flex items-center gap-2 rounded-md border border-border px-3 py-1.5 text-sm">
            <KeyRound className="size-4 text-muted" />
            <span className="font-medium">{t.name}</span>
            <code className="text-xs text-faint">{t.prefix}…</code>
            <span className="text-xs text-faint">used {relativeTime(t.last_used_at)}</span>
            <PlainButton
              className="ml-auto rounded p-1 text-muted hover:text-bad"
              aria-label="Revoke"
              onClick={async () => {
                await api(`/tokens/${t.id}`, { method: "DELETE" });
                mutate();
              }}
            >
              <Trash2 className="size-3.5" />
            </PlainButton>
          </div>
        ))}
      </div>
    </Section>
  );
}
