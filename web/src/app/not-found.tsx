import Link from "next/link";
import { Plane } from "lucide-react";

export const metadata = { title: "Page not found" };

export default function NotFound() {
  return (
    <main className="grid min-h-screen place-items-center bg-bg px-4 text-fg">
      <div className="flex max-w-sm flex-col items-center gap-3 text-center">
        <span className="grid size-12 place-items-center rounded-2xl bg-gradient-to-br from-accent to-[oklch(0.55_0.2_290)] text-white shadow-[var(--shadow)]">
          <Plane className="size-5 -rotate-45" />
        </span>
        <h1 className="text-lg font-semibold">This page doesn&apos;t exist</h1>
        <p className="text-sm text-muted">The link may be old or mistyped.</p>
        <Link href="/" className="mt-1 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:opacity-90">
          Search flights
        </Link>
      </div>
    </main>
  );
}
