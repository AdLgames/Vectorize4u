import type { Metadata } from "next";
import CheckoutSuccess from "@/components/CheckoutSuccess";

export const metadata: Metadata = {
  title: "Payment received",
  robots: { index: false, follow: false },
};

export default function CheckoutSuccessPage() {
  return (
    <div style={{ padding: "40px 20px 64px", maxWidth: 560, display: "grid", gap: "var(--space-5)" }}>
      <CheckoutSuccess />
    </div>
  );
}
