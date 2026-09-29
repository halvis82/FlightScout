import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));
import { emailConfigured, sendEmail } from "@/lib/notify";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("email delivery", () => {
  it("requires both credentials and a sender and never sends while unconfigured", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    vi.stubEnv("RESEND_API_KEY", "");
    vi.stubEnv("ALERT_FROM_EMAIL", "alerts@example.com");
    expect(emailConfigured()).toBe(false);
    vi.stubEnv("RESEND_API_KEY", "test-key");
    vi.stubEnv("ALERT_FROM_EMAIL", "");
    expect(emailConfigured()).toBe(false);
    expect(await sendEmail("user@example.com", "Price alert", "<p>Price dropped</p>")).toBe(false);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("uses the configured sender and reports provider rejection", async () => {
    vi.stubEnv("RESEND_API_KEY", "test-key");
    vi.stubEnv("ALERT_FROM_EMAIL", "FlightScout <alerts@example.com>");
    const fetch = vi.fn().mockResolvedValueOnce({ ok: true }).mockResolvedValueOnce({ ok: false });
    vi.stubGlobal("fetch", fetch);
    expect(emailConfigured()).toBe(true);
    expect(await sendEmail("user@example.com", "Price alert", "<p>Price dropped</p>")).toBe(true);
    const [url, request] = fetch.mock.calls[0];
    expect(url).toBe("https://api.resend.com/emails");
    expect(request.headers.authorization).toBe("Bearer test-key");
    expect(JSON.parse(request.body)).toEqual({
      from: "FlightScout <alerts@example.com>", to: "user@example.com", subject: "Price alert", html: "<p>Price dropped</p>",
    });
    expect(await sendEmail("user@example.com", "Price alert", "<p>Price dropped</p>")).toBe(false);
  });
});
