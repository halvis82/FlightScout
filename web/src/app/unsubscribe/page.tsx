import { eq } from "drizzle-orm";
import Link from "next/link";
import { Plane } from "lucide-react";
import { db, schema } from "@/lib/db";
import { checkUnsubscribe } from "@/lib/email";
import { Unsubscribe } from "./unsubscribe";

export const metadata = { title: "Unsubscribe" };

export default async function UnsubscribePage({ searchParams }: { searchParams: Promise<{ u?: string; s?: string }> }) {
  const { u, s } = await searchParams;
  const valid = checkUnsubscribe(u, s);
  const [user] = valid ? await db.select({ email: schema.user.email }).from(schema.user).where(eq(schema.user.id, u!)) : [];
  return (
    <div className="grid min-h-screen place-items-center px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center justify-center gap-2 text-lg font-semibold">
          <span className="grid size-8 place-items-center rounded-lg bg-accent text-accent-fg">
            <Plane className="size-4 -rotate-45" />
          </span>
          FlightScout
        </div>
        <div className="rounded-xl border border-border bg-surface p-5 text-center shadow-[var(--shadow)]">
          {user ? (
            <Unsubscribe u={u!} s={s!} email={user.email} />
          ) : (
            <>
              <h1 className="text-lg font-semibold">This link doesn&apos;t work</h1>
              <p className="mt-2 text-sm text-muted">
                It may have been cut off. You can turn price emails off in{" "}
                <Link href="/settings" className="text-accent hover:underline">Settings</Link> after signing in.
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
