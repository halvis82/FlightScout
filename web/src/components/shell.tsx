"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import useSWR from "swr";
import { Bell, Compass, Route, Eye, History, LogOut, MapPin, Monitor, Moon, Plane, Search, Settings, Sun } from "lucide-react";
import { cn } from "@/lib/utils";
import { api, fetcher } from "@/lib/client";
import { relativeTime } from "@/lib/format";
import { signOut } from "@/lib/auth-client";
import { useApp } from "./app-context";
import { GuestBanner, ImportGuestData } from "./guest-ui";

const NAV = [
  { href: "/", label: "Search", icon: Search },
  { href: "/explore", label: "Explore", icon: Compass },
  { href: "/trip", label: "Trip", icon: Route },
  { href: "/watches", label: "Watchlist", icon: Eye },
  { href: "/places", label: "Places", icon: MapPin },
  { href: "/history", label: "History", icon: History },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function Shell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const { me } = useApp();

  // First run: send new accounts through onboarding. Guests are never forced.
  useEffect(() => {
    if (me?.user && me.settings && !me.settings.onboarded && path !== "/onboarding") router.replace("/onboarding");
  }, [me, path, router]);

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-40 border-b border-border bg-surface/90 backdrop-blur">
        <div className="mx-auto flex h-12 max-w-7xl items-center gap-2 px-4">
          <Link href="/" className="mr-3 flex items-center gap-1.5 font-semibold tracking-tight">
            <span className="grid size-6 place-items-center rounded-md bg-accent text-accent-fg">
              <Plane className="size-3.5 -rotate-45" />
            </span>
            FlightScout
          </Link>
          <nav className="hidden flex-1 items-center gap-0.5 md:flex">
            {NAV.map((n) => {
              const active = n.href === "/" ? path === "/" : path.startsWith(n.href);
              return (
                <Link
                  key={n.href}
                  href={n.href}
                  className={cn(
                    "rounded-md px-2.5 py-1.5 text-sm font-medium transition-colors",
                    active ? "bg-surface-2 text-fg" : "text-muted hover:text-fg",
                  )}
                >
                  {n.label}
                </Link>
              );
            })}
          </nav>
          <div className="ml-auto flex items-center gap-1">
            <ThemeToggle />
            <AlertsBell />
            <UserMenu />
          </div>
        </div>
      </header>
      <GuestBanner />
      <ImportGuestData />
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 pt-5 pb-24 md:pb-10">{children}</main>
      <nav className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-7 border-t border-border bg-surface/95 backdrop-blur md:hidden">
        {NAV.map((n) => {
          const active = n.href === "/" ? path === "/" : path.startsWith(n.href);
          return (
            <Link
              key={n.href}
              href={n.href}
              className={cn("flex flex-col items-center gap-0.5 py-2 text-[10px]", active ? "text-accent" : "text-muted")}
            >
              <n.icon className="size-4" />
              {n.label}
            </Link>
          );
        })}
      </nav>
    </div>
  );
}

const themeListeners = new Set<() => void>();
function readTheme() {
  try {
    return localStorage.getItem("theme") ?? "system";
  } catch {
    return "system";
  }
}

function ThemeToggle() {
  const theme = useSyncExternalStore(
    (cb) => {
      themeListeners.add(cb);
      return () => themeListeners.delete(cb);
    },
    readTheme,
    () => "system",
  );
  function cycle() {
    const next = theme === "system" ? "light" : theme === "light" ? "dark" : "system";
    try {
      if (next === "system") localStorage.removeItem("theme");
      else localStorage.setItem("theme", next);
    } catch {}
    if (next === "system") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = next;
    themeListeners.forEach((l) => l());
  }
  const Icon = theme === "light" ? Sun : theme === "dark" ? Moon : Monitor;
  return (
    <button onClick={cycle} className="rounded-md p-2 text-muted hover:bg-surface-2 hover:text-fg" title={`Theme: ${theme}`} aria-label="Toggle theme">
      <Icon className="size-4" />
    </button>
  );
}

type Alert = { id: number; message: string; price: number | null; currency: string | null; booking_url: string | null; watchId: number | null; createdAt: string; readAt: string | null };

function AlertsBell() {
  const { data, mutate } = useSWR<{ alerts: Alert[]; unread: number }>("/alerts", fetcher, { refreshInterval: 120_000 });
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);
  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="relative rounded-md p-2 text-muted hover:bg-surface-2 hover:text-fg"
        aria-label="Alerts"
      >
        <Bell className="size-4" />
        {!!data?.unread && (
          <span className="absolute top-1 right-1 grid min-w-3.5 place-items-center rounded-full bg-bad px-0.5 text-[9px] font-bold leading-3.5 text-white">
            {data.unread}
          </span>
        )}
      </button>
      {open && (
        <div className="absolute right-0 z-50 mt-1 w-80 max-w-[calc(100vw-2rem)] overflow-hidden rounded-lg border border-border bg-surface shadow-xl">
          <div className="flex items-center justify-between border-b border-border px-3 py-2">
            <span className="text-sm font-semibold">Price alerts</span>
            {!!data?.unread && (
              <button
                className="text-xs text-accent hover:underline"
                onClick={async () => {
                  await api("/alerts", { body: { all: true } });
                  mutate();
                }}
              >
                Mark all read
              </button>
            )}
          </div>
          <div className="max-h-96 overflow-y-auto">
            {!data?.alerts.length && <div className="px-3 py-6 text-center text-sm text-muted">No alerts yet. Set a target price on a watch to get one.</div>}
            {data?.alerts.map((a) => (
              <Link
                key={a.id}
                href={a.watchId ? `/watches/${a.watchId}` : "/watches"}
                onClick={() => {
                  setOpen(false);
                  if (!a.readAt) api("/alerts", { body: { ids: [a.id] } }).then(() => mutate());
                }}
                className={cn("block border-b border-border px-3 py-2 text-sm last:border-0 hover:bg-surface-2", !a.readAt && "bg-accent-soft/50")}
              >
                <div>{a.message}</div>
                <div className="mt-0.5 text-xs text-faint">{relativeTime(a.createdAt)}</div>
              </Link>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function UserMenu() {
  const { me } = useApp();
  if (me?.guest)
    return (
      <Link href="/login" className="ml-1 inline-flex h-8 items-center rounded-md bg-accent px-3 text-sm font-medium text-accent-fg hover:brightness-110">
        Sign in
      </Link>
    );
  return (
    <button
      onClick={async () => {
        await signOut();
        // full reload so the app switches to guest mode cleanly
        window.location.assign(window.location.origin);
      }}
      className="flex items-center gap-1.5 rounded-md p-2 text-muted hover:bg-surface-2 hover:text-fg"
      title={me?.user ? `Signed in as ${me.user.email}. Click to sign out.` : "Sign out"}
    >
      <span className="hidden max-w-32 truncate text-xs lg:inline">{me?.user?.email}</span>
      <LogOut className="size-4" />
    </button>
  );
}
