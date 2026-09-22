import { enabledSocialProviders } from "@/lib/auth";
import { Suspense } from "react";
import { LoginForm } from "./login-form";

export const metadata = { title: "Sign in · FlightScout" };

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm social={enabledSocialProviders} />
    </Suspense>
  );
}
