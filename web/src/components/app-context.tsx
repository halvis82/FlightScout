"use client";
import { createContext, useCallback, useContext, useMemo, type ReactNode } from "react";
import useSWR, { type KeyedMutator } from "swr";
import { api, fetcher } from "@/lib/client";
import { guestSettings } from "@/lib/guest";
import { formatPrice } from "@/lib/format";
import type { PlannerDefaults, SellerRule } from "@/lib/db/schema";

export type Place = { id: number; label: string; codes: string[]; kind: "home" | "frequent" | "interested"; color?: string | null; notes?: string | null };
export type Settings = {
  currency: string;
  defaultOrigins: string[];
  planner: PlannerDefaults;
  sellerRules: SellerRule[];
  emailAlerts: boolean;
  pushAlerts: boolean;
  onboarded: boolean;
};
type Me = {
  guest: boolean;
  user: { id: string; name: string; email: string } | null;
  settings: Settings;
  features: { push: boolean; email: boolean; engine: boolean; oauth: string[] };
};

type Ctx = {
  me?: Me;
  settings?: Settings;
  places: Place[];
  refreshMe: KeyedMutator<Me>;
  refreshPlaces: KeyedMutator<Place[]>;
  currency: string;
  convert: (amount: number, from: string, to?: string) => number;
  money: (amount: number | null | undefined, from: string, opts?: { compact?: boolean }) => string;
};

const AppCtx = createContext<Ctx | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  // Guests have no server settings; theirs live in localStorage.
  const { data: me, mutate: refreshMe } = useSWR<Me>(
    "/me",
    async () => {
      const m = await api<Omit<Me, "guest">>("/me");
      return { ...m, guest: !m.user, settings: m.user ? m.settings : (guestSettings() as unknown as Settings) };
    },
    { revalidateOnFocus: false },
  );
  const { data: places, mutate: refreshPlaces } = useSWR<Place[]>("/places", fetcher, { revalidateOnFocus: false });
  const { data: fx } = useSWR<{ rates: Record<string, number> }>("/fx", fetcher, { revalidateOnFocus: false });
  const currency = me?.settings.currency ?? "USD";

  const convert = useCallback(
    (amount: number, from: string, to = currency) => {
      if (from === to || !fx) return amount;
      const f = fx.rates[from];
      const t = fx.rates[to];
      return f && t ? (amount / f) * t : amount;
    },
    [fx, currency],
  );
  const money = useCallback(
    (amount: number | null | undefined, from: string, opts?: { compact?: boolean }) =>
      amount == null ? "–" : fx || from === currency ? formatPrice(convert(amount, from), currency, opts) : formatPrice(amount, from, opts),
    [convert, currency, fx],
  );

  const value = useMemo<Ctx>(
    () => ({ me, settings: me?.settings, places: places ?? [], refreshMe, refreshPlaces, currency, convert, money }),
    [me, places, refreshMe, refreshPlaces, currency, convert, money],
  );
  return <AppCtx.Provider value={value}>{children}</AppCtx.Provider>;
}

export function useApp() {
  const c = useContext(AppCtx);
  if (!c) throw new Error("useApp outside AppProvider");
  return c;
}
