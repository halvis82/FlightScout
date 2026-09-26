import "server-only";

// ECB reference rates (base EUR) from frankfurter.dev, cached in memory for 6h.
let cached: { at: number; rates: Record<string, number> } | null = null;

export async function getRates(): Promise<Record<string, number>> {
  if (cached && Date.now() - cached.at < 6 * 3600_000) return cached.rates;
  try {
    const res = await fetch("https://api.frankfurter.dev/v1/latest?base=EUR", {
      next: { revalidate: 21600 },
    });
    const j = (await res.json()) as { rates?: Record<string, number> };
    // an answer without rates (an outage page) must not replace good ones for hours
    if (!j.rates || typeof j.rates.USD !== "number") throw new Error("no rates in the answer");
    const rates = { ...j.rates, EUR: 1 };
    cached = { at: Date.now(), rates };
    return rates;
  } catch {
    return cached?.rates ?? { EUR: 1, USD: 1.1, NOK: 11.7, GBP: 0.85, MXN: 20 };
  }
}

export function convertWith(rates: Record<string, number>, amount: number, from: string, to: string) {
  if (from === to) return amount;
  const f = rates[from.toUpperCase()];
  const t = rates[to.toUpperCase()];
  if (!f || !t) return amount;
  return (amount / f) * t;
}

export function hasRate(rates: Record<string, number>, cur: string) {
  return typeof cur === "string" && Boolean(rates[cur.toUpperCase()]);
}

export async function convert(amount: number, from: string, to: string) {
  return convertWith(await getRates(), amount, from, to);
}
