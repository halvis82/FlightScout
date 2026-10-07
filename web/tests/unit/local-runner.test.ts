import { afterEach, beforeEach, expect, test, vi } from "vitest";

beforeEach(() => {
  vi.resetModules();
  vi.useFakeTimers();
  const values = new Map<string, string>();
  vi.stubGlobal("window", {});
  vi.stubGlobal("document", { visibilityState: "visible" });
  vi.stubGlobal("navigator", { permissions: { query: async () => ({ state: "granted" }) } });
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => values.get(k) ?? null,
    setItem: (k: string, v: string) => values.set(k, v),
    removeItem: (k: string) => values.delete(k),
  });
});
afterEach(() => { vi.clearAllTimers(); vi.useRealTimers(); vi.unstubAllGlobals(); });

function health(lifecycle?: object) {
  return { ok: true, json: async () => ({ ok: true, local: true, api: 3, lifecycle }) };
}

test("idle deadline stops status polling; a search reconnects", async () => {
  const fetch = vi.fn().mockResolvedValue(health({ idle_minutes: 120, idle_expires_at: Date.now() / 1000 + 60, active_requests: 0 }));
  vi.stubGlobal("fetch", fetch);
  const runner = await import("@/lib/local-runner");
  runner.startLocalRunnerProbe();
  await vi.advanceTimersByTimeAsync(30_000);
  expect(fetch).toHaveBeenCalledTimes(2);
  await vi.advanceTimersByTimeAsync(90_000);
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(runner.localRunnerActive()).toBe(false);
  await runner.runnerKnown();
  expect(fetch).toHaveBeenCalledTimes(3);
});

test("legacy runner without a deadline is not polled repeatedly", async () => {
  const fetch = vi.fn().mockResolvedValue(health());
  vi.stubGlobal("fetch", fetch);
  const runner = await import("@/lib/local-runner");
  runner.startLocalRunnerProbe();
  await vi.advanceTimersByTimeAsync(300_000);
  expect(fetch).toHaveBeenCalledTimes(1);
});

test("disabling while connecting persists and prevents automatic wake", async () => {
  let resolve!: (v: ReturnType<typeof health>) => void;
  const fetch = vi.fn(() => new Promise(r => { resolve = r; }));
  vi.stubGlobal("fetch", fetch);
  const runner = await import("@/lib/local-runner");
  const pending = runner.connectLocalRunner();
  runner.setLocalRunnerDisabled(true);
  resolve(health());
  await pending;
  expect(runner.localRunnerActive()).toBe(false);
  await runner.runnerKnown();
  expect(fetch).toHaveBeenCalledTimes(1);
});
