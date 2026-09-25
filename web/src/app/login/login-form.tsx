"use client";
import { useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { Fingerprint, Plane } from "lucide-react";
import { authClient, signIn, signUp } from "@/lib/auth-client";
import { Button, ErrorNote, Field, Input, Segmented } from "@/components/ui";

export function LoginForm({ social }: { social: string[] }) {
  const params = useSearchParams();
  const next = params.get("next") || "/";
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    const res =
      mode === "signin"
        ? await signIn.email({ email, password })
        : await signUp.email({ email, password, name: name || email.split("@")[0] });
    setBusy(false);
    if (res.error) setErr(res.error.message ?? "Something went wrong");
    // full reload so the app leaves guest mode cleanly
    else window.location.href = next;
  }

  async function passkey() {
    setErr(null);
    const res = await authClient.signIn.passkey();
    if (res?.error) setErr(res.error.message ?? "Passkey sign in failed");
    else window.location.href = next;
  }

  return (
    <div className="grid min-h-screen place-items-center px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center justify-center gap-2 text-lg font-semibold">
          <span className="grid size-8 place-items-center rounded-lg bg-accent text-accent-fg">
            <Plane className="size-4 -rotate-45" />
          </span>
          FlightScout
        </div>
        <div className="rounded-xl border border-border bg-surface p-5 shadow-[var(--shadow)]">
          <div className="mb-4 flex justify-center">
            <Segmented
              value={mode}
              onChange={setMode}
              options={[
                { value: "signin", label: "Sign in" },
                { value: "signup", label: "Create account" },
              ]}
            />
          </div>
          <form onSubmit={submit} className="space-y-3">
            {mode === "signup" && (
              <Field label="Name">
                <Input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
              </Field>
            )}
            <Field label="Email">
              <Input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email webauthn" />
            </Field>
            <Field label="Password" hint={mode === "signup" ? `At least 8 characters.${process.env.NEXT_PUBLIC_OPEN_SIGNUP === "1" ? "" : " Sign ups are invite only for now."}` : undefined}>
              <Input
                type="password"
                required
                minLength={8}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete={mode === "signin" ? "current-password webauthn" : "new-password"}
              />
            </Field>
            {err && <ErrorNote>{err}</ErrorNote>}
            <Button type="submit" variant="primary" className="w-full" loading={busy}>
              {mode === "signin" ? "Sign in" : "Create account"}
            </Button>
          </form>
          {mode === "signin" && (
            <>
              <div className="my-4 flex items-center gap-3 text-xs text-faint">
                <div className="h-px flex-1 bg-border" /> or <div className="h-px flex-1 bg-border" />
              </div>
              <div className="space-y-2">
                <Button className="w-full" onClick={passkey}>
                  <Fingerprint className="size-4" /> Sign in with a passkey
                </Button>
                {social.map((p) => (
                  <Button key={p} className="w-full" onClick={() => signIn.social({ provider: p as "github" | "google", callbackURL: next })}>
                    Continue with {p === "github" ? "GitHub" : "Google"}
                  </Button>
                ))}
              </div>
            </>
          )}
        </div>
        <p className="mt-4 text-center text-sm">
          <Link href="/" className="text-accent hover:underline">
            Continue as a guest
          </Link>
        </p>
        <p className="mt-2 text-center text-xs text-faint">
          Search, smart routes, explore and a local watchlist work without an account. No bookings or payments happen here.
        </p>
      </div>
    </div>
  );
}
