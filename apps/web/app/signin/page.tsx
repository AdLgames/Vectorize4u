import type { Metadata } from "next";
import { Suspense } from "react";
import SignInScreen from "@/components/SignInScreen";

export const metadata: Metadata = {
  title: "Sign in",
  robots: { index: false, follow: false },
};

export default function SignInPage() {
  return (
    <div style={{ padding: "40px 20px 64px", maxWidth: 460, display: "grid", gap: "var(--space-5)" }}>
      <h1 style={{ fontSize: "var(--text-h1)", margin: 0 }}>Sign in</h1>
      <Suspense fallback={null}>
        <SignInScreen />
      </Suspense>
    </div>
  );
}
