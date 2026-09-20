import type { Metadata } from "next";
import AccountPanel from "@/components/AccountPanel";

export const metadata: Metadata = {
  title: "Your account",
  robots: { index: false, follow: false },
};

export default function AccountPage() {
  return (
    <div style={{ padding: "40px 20px 64px", display: "grid", gap: "var(--space-5)" }}>
      <h1 style={{ fontSize: "var(--text-h1)", margin: 0 }}>Account</h1>
      <AccountPanel />
    </div>
  );
}
