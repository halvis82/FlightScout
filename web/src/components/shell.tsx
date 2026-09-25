"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { Check, ChevronDown, History, LogIn, LogOut, Monitor, Moon, Plane, Settings, Sun, User, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { api } from "@/lib/client";
import { signOut } from "@/lib/auth-client";
import { startLocalRunnerProbe, useLocalRunner } from "@/lib/local-runner";
import { useExtension } from "@/lib/extension";
import { CURRENCIES } from "@/lib/types";
import { useApp } from "./app-context";
import { GuestBanner, ImportGuestData } from "./guest-ui";
import { openPanel, toastStore } from "./stores";
import { PlainButton, Tip, useDismiss } from "./ui";
import { WatchlistButton, WatchlistPanel } from "./watchlist-panel";

const NAV = [
  { href: "/", label: "Search" },
  { href: "/airlines", label: "Airlines" },
];

export function Shell({ children }: { children: ReactNode }) {
  const path = usePathname();

  useEffect(() => {
    startLocalRunnerProbe();
    // ?panel=watchlist (old /watches links) opens the drawer
    const p = new URLSearchParams(window.location.search).get("panel");
    if (p === "watchlist") openPanel("watchlist");
  }, []);

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-40 border-b border-border bg-surface/85 backdrop-blur-md">
        <div className="mx-auto flex h-14 max-w-7xl items-center gap-1 px-3 sm:gap-2 sm:px-4">
          <Link href="/?new=1" className="mr-2 flex shrink-0 items-center gap-2 text-[15px] font-semibold tracking-tight">
            <span className="grid size-8 place-items-center rounded-xl bg-gradient-to-br from-accent to-[oklch(0.55_0.2_290)] text-white shadow-[var(--shadow)]">
              <Plane className="size-4 -rotate-45" />
            </span>
            <span className="hidden min-[400px]:inline">FlightScout</span>
          </Link>
          <nav className="hidden items-center gap-0.5 sm:flex">
            {NAV.map((n) => {
              const active = n.href === "/" ? path === "/" : path.startsWith(n.href);
              return (
                <Link
                  key={n.href}
                  href={n.href}
                  className={cn("rounded-lg px-3 py-1.5 text-sm font-medium transition-colors", active ? "bg-surface-2 text-fg" : "text-muted hover:text-fg")}
                >
                  {n.label}
                </Link>
              );
            })}
          </nav>
          <div className="ml-auto flex items-center gap-0.5 sm:gap-1">
            <LocalRunnerPill />
            <CurrencyPicker />
            <WatchlistButton />
            <Link
              href="/settings"
              className={cn("grid size-9 place-items-center rounded-lg text-muted hover:bg-surface-2 hover:text-fg", path.startsWith("/settings") && "bg-surface-2 text-fg")}
              aria-label="Settings"
              title="Settings"
            >
              <Settings className="size-4" />
            </Link>
            <AccountMenu />
          </div>
        </div>
      </header>
      <GuestBanner />
      <ImportGuestData />
      <main className="mx-auto w-full max-w-7xl flex-1 px-3 pt-5 pb-16 sm:px-4">{children}</main>
      <WatchlistPanel />
      <Toaster />
    </div>
  );
}

function LocalRunnerPill() {
  const lr = useLocalRunner();
  const ext = useExtension();
  if (!lr.active && !ext) return null;
  const how = lr.active ? `the local runner (flightscout serve${lr.version ? ` ${lr.version}` : ""})` : `the FlightScout Helper extension ${ext}`;
  return (
    <Tip side="bottom" label={`Google Flights searches run from your own IP through ${how}, so they're never blocked or rate limited.`}>
      <Link href="/settings#own-ip" className="hidden items-center gap-1.5 rounded-full border border-good/30 bg-good-soft px-2.5 py-1 text-xs font-medium text-good md:inline-flex">
        <span className="size-1.5 rounded-full bg-good" /> Your IP
      </Link>
    </Tip>
  );
}

function CurrencyPicker() {
  const { settings, refreshMe } = useApp();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setOpen(false), []);
  useDismiss(ref, open, close);
  const cur = settings?.currency ?? "USD";
  async function pick(c: string) {
    setOpen(false);
    if (c === cur) return;
    await api("/settings", { method: "PATCH", body: { currency: c } });
    refreshMe();
  }
  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="inline-flex h-9 items-center gap-1 rounded-lg px-2.5 text-sm font-semibold text-fg hover:bg-surface-2"
        aria-label={`Currency: ${cur}`}
        aria-expanded={open}
      >
        {cur}
        <ChevronDown className="size-3.5 text-muted" />
      </button>
      {open && (
        <div className="pop-in absolute right-0 z-50 mt-1 w-44 overflow-hidden rounded-xl border border-border bg-surface p-1 shadow-[var(--shadow-lg)]">
          {CURRENCIES.map((c) => (
            <button
              key={c}
              role="menuitemradio"
              aria-checked={c === cur}
              onClick={() => pick(c)}
              className="flex w-full items-center justify-between rounded-lg px-2.5 py-2 text-sm hover:bg-surface-2"
            >
              <span>
                <span className="font-semibold">{c}</span> <span className="text-muted">{CURRENCY_NAMES[c]}</span>
              </span>
              {c === cur && <Check className="size-4 text-accent" />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

const CURRENCY_NAMES: Record<string, string> = { NOK: "Krone", EUR: "Euro", USD: "Dollar", GBP: "Pound", MXN: "Peso" };

const themeListeners = new Set<() => void>();
function readTheme() {
  try {
    return localStorage.getItem("theme") ?? "system";
  } catch {
    return "system";
  }
}
function setTheme(next: string) {
  try {
    if (next === "system") localStorage.removeItem("theme");
    else localStorage.setItem("theme", next);
  } catch {}
  if (next === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = next;
  themeListeners.forEach((l) => l());
}

function AccountMenu() {
  const { me } = useApp();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setOpen(false), []);
  useDismiss(ref, open, close);
  const theme = useSyncExternalStore(
    (cb) => {
      themeListeners.add(cb);
      return () => themeListeners.delete(cb);
    },
    readTheme,
    () => "system",
  );
  const initial = me?.user ? (me.user.name || me.user.email).slice(0, 1).toUpperCase() : null;
  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="ml-0.5 grid size-9 place-items-center rounded-full text-muted hover:bg-surface-2 hover:text-fg"
        aria-label="Account menu"
        aria-expanded={open}
      >
        {initial ? (
          <span className="grid size-7 place-items-center rounded-full bg-accent text-xs font-semibold text-accent-fg">{initial}</span>
        ) : (
          <span className="grid size-7 place-items-center rounded-full bg-surface-2 text-muted">
            <User className="size-4" />
          </span>
        )}
      </button>
      {open && (
        <div className="pop-in absolute right-0 z-50 mt-1 w-64 overflow-hidden rounded-xl border border-border bg-surface shadow-[var(--shadow-lg)]">
          <div className="border-b border-border px-3 py-2.5">
            {me?.user ? (
              <>
                <div className="truncate text-sm font-medium">{me.user.name}</div>
                <div className="truncate text-xs text-muted">{me.user.email}</div>
              </>
            ) : (
              <>
                <div className="text-sm font-medium">Guest</div>
                <div className="text-xs text-muted">Your data stays in this browser.</div>
              </>
            )}
          </div>
          <div className="p-1">
            <div className="px-2.5 pt-1.5 pb-1 text-[11px] font-medium text-faint">Theme</div>
            <div className="grid grid-cols-3 gap-1 px-1.5 pb-1.5">
              {(
                [
                  ["light", "Light", Sun],
                  ["dark", "Dark", Moon],
                  ["system", "Auto", Monitor],
                ] as const
              ).map(([v, l, I]) => (
                <button
                  key={v}
                  onClick={() => setTheme(v)}
                  className={cn(
                    "flex flex-col items-center gap-1 rounded-lg border py-2 text-xs",
                    theme === v ? "border-accent bg-accent-soft text-accent" : "border-border text-muted hover:text-fg",
                  )}
                >
                  <I className="size-4" />
                  {l}
                </button>
              ))}
            </div>
            <Link href="/settings" onClick={close} className="flex items-center gap-2 rounded-lg px-2.5 py-2 text-sm hover:bg-surface-2">
              <Settings className="size-4 text-muted" /> Settings
            </Link>
            <Link href="/history" onClick={close} className="flex items-center gap-2 rounded-lg px-2.5 py-2 text-sm hover:bg-surface-2">
              <History className="size-4 text-muted" /> History
            </Link>
            {me?.guest ? (
              <Link href="/login" onClick={close} className="flex items-center gap-2 rounded-lg px-2.5 py-2 text-sm font-medium text-accent hover:bg-surface-2">
                <LogIn className="size-4" /> Sign in
              </Link>
            ) : (
              <PlainButton
                onClick={async () => {
                  await signOut();
                  window.location.assign(window.location.origin);
                }}
                className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-sm hover:bg-surface-2"
              >
                <LogOut className="size-4 text-muted" /> Sign out
              </PlainButton>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function Toaster() {
  const toasts = toastStore.use();
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-4 z-[60] flex flex-col items-center gap-2 px-3">
      {toasts.map((t) => (
        <div
          key={t.id}
          className="slide-up pointer-events-auto flex max-w-md items-center gap-3 rounded-xl bg-fg px-4 py-2.5 text-sm text-bg shadow-[var(--shadow-lg)]"
          role="status"
        >
          <span className="min-w-0">{t.text}</span>
          {t.action &&
            (t.action.href ? (
              <Link href={t.action.href} className="shrink-0 font-semibold underline-offset-2 hover:underline">
                {t.action.label}
              </Link>
            ) : (
              <button onClick={t.action.onClick} className="shrink-0 font-semibold underline-offset-2 hover:underline">
                {t.action.label}
              </button>
            ))}
          <button
            onClick={() => toastStore.set(toastStore.get().filter((x) => x.id !== t.id))}
            className="shrink-0 opacity-60 hover:opacity-100"
            aria-label="Dismiss"
          >
            <X className="size-3.5" />
          </button>
        </div>
      ))}
    </div>
  );
}
