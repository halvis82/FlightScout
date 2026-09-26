import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { auth, enabledSocialProviders } from "@/lib/auth";
import { Suspense } from "react";
import { LoginForm } from "./login-form";
import { safeNext } from "@/lib/safe-next";

export const metadata = { title: "Sign in" };

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ next?: string }> }) {
  // already signed in: nothing to do here
  let signedIn = false;
  try {
    signedIn = Boolean(await auth.api.getSession({ headers: await headers() }));
  } catch {
    /* no database: show the form */
  }
  if (signedIn) {
    redirect(safeNext((await searchParams).next));
  }
  return (
    <Suspense>
      <LoginForm social={enabledSocialProviders} />
    </Suspense>
  );
}
