import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));
import { checkUnsubscribe, confirmEmail, priceAlertEmail, readableRoute, unsubscribeQuery } from "@/lib/email";

const airports = [
  { iata: "OSL", city: "Oslo" },
  { iata: "TRF", city: "Oslo (Torp)" },
  { iata: "CDG", city: "Paris" },
  { iata: "BVA", city: "Paris (Beauvais)" },
];

afterEach(() => vi.unstubAllGlobals());

describe("emails", () => {
  it("unsubscribe links are signed per user", () => {
    const q = new URLSearchParams(unsubscribeQuery("user-1"));
    expect(checkUnsubscribe("user-1", q.get("s"))).toBe(true);
    expect(checkUnsubscribe("user-2", q.get("s"))).toBe(false);
    expect(checkUnsubscribe("user-1", "nope")).toBe(false);
    expect(checkUnsubscribe(null, q.get("s"))).toBe(false);
  });

  it("names routes by city and builds an alert with a fare button and unsubscribe", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => airports }));
    expect(await readableRoute("OSL/TRF to CDG/BVA")).toBe("Oslo to Paris");
    expect(await readableRoute("My <b> trip")).toBe("My <b> trip");
    const mail = await priceAlertEmail({
      user: { id: "u1", name: "Halvor Hafnor", email: "a@example.com" },
      watch: { id: 9, name: "OSL/TRF to CDG/BVA", tripType: "oneway", departStart: "2026-12-26", departEnd: "2026-12-26", nightsMin: null, nightsMax: null, adults: 1, currency: "USD" },
      price: 100,
      prev: 122,
      reasons: ["dropped 18% from $122 to $100"],
      bookingUrl: "https://airline.example/book?a=1&b=2",
    });
    expect(mail.subject).toBe("Oslo to Paris is now $100");
    expect(mail.html).toContain("Hi Halvor,");
    expect(mail.html).toContain("Price drop: Oslo to Paris");
    expect(mail.html).toContain('href="https://airline.example/book?a=1&amp;b=2"');
    expect(mail.html).toContain("/unsubscribe?u=u1&amp;s=");
    expect(mail.unsubscribe).toMatch(/\/api\/v1\/unsubscribe\?u=u1&s=/);
    expect(mail.text).toContain("See this fare: https://airline.example/book?a=1&b=2");
    expect(mail.text).toContain("One way · leaving Dec 26, 2026 · 1 traveler");
  });

  it("escapes what users typed", () => {
    const mail = confirmEmail({ name: "<script>", email: "a@example.com" }, "https://x/confirm?t=1");
    expect(mail.html).not.toContain("<script>");
    expect(mail.unsubscribe).toBeUndefined();
  });
});
