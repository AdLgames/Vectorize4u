import type { Metadata } from "next";
import AccountPanel from "@/components/AccountPanel";

export const metadata: Metadata = {
  title: "Your account",
  robots: { index: false, follow: false },
};

export default function AccountPage() {
  return (
    <div className="mx-auto max-w-4xl space-y-6 px-4 py-10">
      <h1 className="text-3xl font-semibold tracking-tight">Your account</h1>
      <AccountPanel />
    </div>
  );
}
