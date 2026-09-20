import type { Metadata } from "next";
import Link from "next/link";
import { Faq } from "@/components/JsonLd";
import {
  ENDPOINTS,
  ERROR_CODES,
  OPTIONS,
  PRESIGNED,
  QUICKSTART,
  WEBHOOK_VERIFY,
} from "@/lib/apiReference";

/**
 * §9 — the public API docs. They rank for "image to svg api", and they are
 * the whole recruitment path for the developer tier: nobody buys an API
 * plan off a pricing page.
 *
 * The reference content lives in `lib/apiReference.ts` so the API test
 * suite can check it against the live OpenAPI schema.
 */

export const metadata: Metadata = {
  title: "Image to vector API",
  description:
    "A REST API that converts PNG and JPEG to SVG, DXF, PDF and EPS. Synchronous under 8 seconds, signed webhooks, idempotent POSTs, and a hard cap on usage billing.",
  alternates: { canonical: "/api" },
};

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "https://api.vectorize.example";

const FAQ = [
  {
    question: "Is the API synchronous or asynchronous?",
    answer:
      "Both, without you having to choose in advance. POST /v1/vectorize holds the connection for up to 8 seconds; if the trace finishes inside that window you get 200 and the result, and if it doesn't you get 202 and a job id to poll or a webhook to wait on. Send Prefer: respond-async to skip the wait entirely.",
  },
  {
    question: "What am I charged for?",
    answer:
      "One credit per successfully completed API job, debited on completion. Failed jobs are never billed, and re-tracing the same source image with different options is free — every revision shares one charge.",
  },
  {
    question: "Can a runaway retry loop produce a huge invoice?",
    answer:
      "No. Usage beyond your plan is capped at three times the plan price per billing period, and requests are refused at the door once you reach it rather than run and billed. You can remove the cap deliberately from your account page; it is never removed for you.",
  },
  {
    question: "How do I verify a webhook came from you?",
    answer:
      "Each delivery carries X-Vectorize-Timestamp and X-Vectorize-Signature, an HMAC-SHA256 over the timestamp, a dot, and the exact request body, keyed with your signing secret. Compare it in constant time and reject anything with a timestamp more than a few minutes old.",
  },
  {
    question: "Do you store my images?",
    answer:
      "Only for the retention window of your plan, and DELETE /v1/jobs/{id} purges the source and the outputs immediately. Statistics about the job survive deletion; pixels do not.",
  },
];

const mono = {
  fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
  fontSize: "var(--text-sm)",
};

function Code({ children }: { children: string }) {
  return (
    <pre
      style={{
        ...mono,
        margin: 0,
        padding: "var(--space-4)",
        background: "var(--ink-25)",
        border: "1px solid var(--ink-100)",
        borderRadius: 10,
        overflowX: "auto",
        lineHeight: 1.55,
      }}
    >
      <code>{children}</code>
    </pre>
  );
}

function Section({
  id,
  title,
  children,
}: {
  id: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} style={{ display: "grid", gap: "var(--space-3)", maxWidth: "76ch" }}>
      <h2 style={{ fontSize: "var(--text-h2)", margin: 0 }}>{title}</h2>
      {children}
    </section>
  );
}

const p = { color: "var(--ink-500)", margin: 0 };
const cell: React.CSSProperties = {
  textAlign: "left",
  verticalAlign: "top",
  padding: "10px 12px",
  borderBottom: "1px solid var(--ink-100)",
};

export default function ApiDocsPage() {
  return (
    <div style={{ padding: "40px 20px 80px", display: "grid", gap: "var(--space-7)" }}>
      <div style={{ maxWidth: "68ch", display: "grid", gap: "var(--space-3)" }}>
        <h1 style={{ fontSize: "var(--text-h1)", margin: 0 }}>Image to vector API</h1>
        <p style={{ fontSize: "var(--text-lg)", ...p }}>
          One POST turns a raster image into an SVG, DXF, PDF or EPS. It is the same
          engine the web app uses: several traces run in parallel, each is rendered back
          to pixels and scored against the cleaned original, and the best one is what you
          get.
        </p>
        <p style={p}>
          Base URL <code style={mono}>{API_BASE}</code>. Everything lives under{" "}
          <code style={mono}>/v1</code>. The machine-readable schema is at{" "}
          <a href={`${API_BASE}/openapi.json`}>/openapi.json</a>, and an interactive
          version at <a href={`${API_BASE}/docs`}>/docs</a>.
        </p>
      </div>

      <Section id="auth" title="Authentication">
        <p style={p}>
          Send your key as a bearer token. Keys start with{" "}
          <code style={mono}>v4u_live_</code>, are created on your{" "}
          <Link href="/account">account page</Link> or via{" "}
          <code style={mono}>POST /v1/account/keys</code>, and are shown exactly once — we
          store only a SHA-256 hash, so a lost key is replaced rather than recovered.
        </p>
        <Code>{`Authorization: Bearer v4u_live_...`}</Code>
        <p style={p}>
          Revoking a key takes effect immediately. Rate limits are counted per key, so a
          noisy integration can be cut off without touching the others.
        </p>
      </Section>

      <Section id="quickstart" title="Quickstart">
        <p style={p}>
          The shortest useful call: post the file, ask for SVG and DXF, and fix the
          physical width at 100 mm so it opens at that size in cutting software.
        </p>
        <Code>{QUICKSTART}</Code>
        <p style={p}>
          For anything above a few megabytes, use the presigned flow instead. The bytes go
          straight to storage, so there is no request-body ceiling in the way and a failed
          upload costs you nothing.
        </p>
        <Code>{PRESIGNED}</Code>
      </Section>

      <Section id="sync" title="Waiting, or not">
        <p style={p}>
          <code style={mono}>POST /v1/vectorize</code> holds the connection for up to 8
          seconds. Finished inside the window → <code style={mono}>200</code> with the
          result. Not finished → <code style={mono}>202</code> with the job id, which you
          poll at <code style={mono}>GET /v1/jobs/&#123;id&#125;</code> or wait for by
          webhook. Send <code style={mono}>Prefer: respond-async</code> to get the{" "}
          <code style={mono}>202</code> immediately.
        </p>
        <p style={p}>
          The point of the hold window is that neither side has to predict how long a
          trace takes: a small logo is a synchronous call, a 6000px scan is a job, and
          your code is the same either way.
        </p>
      </Section>

      <Section id="idempotency" title="Idempotency">
        <p style={p}>
          Every POST accepts an <code style={mono}>Idempotency-Key</code> header. A retry
          carrying the same key returns the original job and is never charged twice.
          Reusing a key with a different body is a <code style={mono}>409</code>, because
          silently returning the wrong job would be worse than failing.
        </p>
      </Section>

      <Section id="endpoints" title="Endpoints">
        <table style={{ borderCollapse: "collapse", width: "100%", ...mono }}>
          <tbody>
            {ENDPOINTS.map((endpoint) => (
              <tr key={`${endpoint.method} ${endpoint.path}`}>
                <td style={{ ...cell, whiteSpace: "nowrap", color: "var(--cyan-strong)" }}>
                  {endpoint.method}
                </td>
                <td style={{ ...cell, whiteSpace: "nowrap" }}>{endpoint.path}</td>
                <td style={{ ...cell, fontFamily: "inherit" }}>
                  <div>{endpoint.summary}</div>
                  {endpoint.detail ? (
                    <div style={{ color: "var(--ink-500)", fontSize: "var(--text-sm)" }}>
                      {endpoint.detail}
                    </div>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section id="options" title="Options">
        <p style={p}>
          Passed as <code style={mono}>options</code> on{" "}
          <code style={mono}>/v1/vectorize</code>, <code style={mono}>/v1/batch</code> and{" "}
          <code style={mono}>/v1/jobs/&#123;id&#125;/tweak</code>. Every one of them has a
          default that works; reach for them when you know something about the image that
          we cannot see.
        </p>
        <table style={{ borderCollapse: "collapse", width: "100%" }}>
          <tbody>
            {OPTIONS.map((option) => (
              <tr key={option.name}>
                <td style={{ ...cell, ...mono, whiteSpace: "nowrap" }}>{option.name}</td>
                <td style={{ ...cell, ...mono, color: "var(--ink-500)" }}>{option.type}</td>
                <td style={{ ...cell, ...mono, color: "var(--ink-500)" }}>{option.default}</td>
                <td style={{ ...cell, color: "var(--ink-500)" }}>{option.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section id="response" title="What comes back">
        <Code>{`{
  "id": "job_7f3c...",
  "status": "complete",
  "classification": "logo_flat",
  "credits_charged": 1,
  "score": {
    "score_version": "s3",
    "total": 0.94,
    "fidelity": 0.97,
    "ssim": 0.96,
    "edge_f1": 0.93,
    "color": 0.98,
    "node_count": 812,
    "path_count": 14
  },
  "warnings": ["source_is_small"],
  "outputs": { "svg": "https://...", "dxf": "https://..." }
}`}</Code>
        <p style={p}>
          <code style={mono}>fidelity</code> is how closely the trace matches the cleaned
          original; <code style={mono}>total</code> also accounts for how many points it
          took to get there, and is what the engine selects on. Both are reported with a{" "}
          <code style={mono}>score_version</code>: never compare scores across versions,
          because the weights change when the scoring does.
        </p>
        <p style={p}>
          <code style={mono}>warnings</code> is the honest part. A small or heavily
          compressed source is told to you before you pay, not after.
        </p>
      </Section>

      <Section id="webhooks" title="Webhooks">
        <p style={p}>
          Pass <code style={mono}>webhook_url</code> on a job or a batch and we POST to it
          when the work finishes — <em>and when it fails</em>, because silence on failure
          means your queue waits forever. HTTPS only, no redirects followed, and the
          destination is re-checked against private address ranges at delivery time, not
          only when you set it.
        </p>
        <Code>{WEBHOOK_VERIFY}</Code>
        <p style={p}>
          Deliveries are retried with exponential backoff up to five times. Treat them as
          at-least-once and key off <code style={mono}>job_id</code>.
        </p>
      </Section>

      <Section id="errors" title="Errors">
        <p style={p}>
          Errors are problem documents with a stable{" "}
          <code style={mono}>error_code</code>. Branch on that, never on the prose.
        </p>
        <table style={{ borderCollapse: "collapse", width: "100%" }}>
          <tbody>
            {ERROR_CODES.map((error) => (
              <tr key={error.code}>
                <td style={{ ...cell, ...mono, whiteSpace: "nowrap" }}>{error.code}</td>
                <td style={{ ...cell, ...mono, color: "var(--ink-500)" }}>{error.status}</td>
                <td style={{ ...cell, color: "var(--ink-500)" }}>{error.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section id="limits" title="Limits and billing">
        <p style={p}>
          The API plan is $29/month: 500 credits, then $0.04 per credit, with unused
          credits rolling over up to three times the plan&rsquo;s monthly grant. Rate limits are
          per key and reported on every response as{" "}
          <code style={mono}>RateLimit-Limit</code> and{" "}
          <code style={mono}>RateLimit-Remaining</code>; a <code style={mono}>429</code>{" "}
          always carries <code style={mono}>Retry-After</code>. Ask{" "}
          <code style={mono}>GET /v1/limits</code> rather than hard-coding them.
        </p>
        <p style={p}>
          Usage billing is capped at three times the plan price per period. At the cap we
          refuse new work with <code style={mono}>overage_cap_reached</code> instead of
          running it and invoicing you for it. Removing the cap is a deliberate act on
          your account page, and it is the only way the bill goes higher.
        </p>
      </Section>

      <Faq items={FAQ} />
    </div>
  );
}
