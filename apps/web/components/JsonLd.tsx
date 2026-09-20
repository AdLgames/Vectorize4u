/**
 * JSON-LD for the SEO pages (§9).
 *
 * `SoftwareApplication` + `FAQPage` are what actually earn rich results for
 * converter queries; they ship with the landing pages, not later.
 */

export function SoftwareApplicationLd({ name, description }: { name: string; description: string }) {
  const data = {
    "@context": "https://schema.org",
    "@type": "SoftwareApplication",
    name,
    description,
    applicationCategory: "DesignApplication",
    operatingSystem: "Web",
    offers: [
      { "@type": "Offer", price: "0", priceCurrency: "USD", name: "Free previews" },
      { "@type": "Offer", price: "9", priceCurrency: "USD", name: "50-download credit pack" },
      { "@type": "Offer", price: "12", priceCurrency: "USD", name: "Starter, per month" },
      { "@type": "Offer", price: "29", priceCurrency: "USD", name: "Pro, per month" },
    ],
  };
  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{ __html: JSON.stringify(data) }}
    />
  );
}

export function FaqLd({ items }: { items: { question: string; answer: string }[] }) {
  const data = {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: items.map((item) => ({
      "@type": "Question",
      name: item.question,
      acceptedAnswer: { "@type": "Answer", text: item.answer },
    })),
  };
  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{ __html: JSON.stringify(data) }}
    />
  );
}

export function Faq({ items }: { items: { question: string; answer: string }[] }) {
  return (
    <section aria-labelledby="faq-heading" style={{ display: "grid", gap: "var(--space-4)", maxWidth: "68ch" }}>
      <h2 id="faq-heading" style={{ fontSize: "var(--text-h2)", margin: 0 }}>
        Questions
      </h2>
      <dl style={{ display: "grid", gap: "var(--space-4)", margin: 0 }}>
        {items.map((item) => (
          <div key={item.question}>
            <dt style={{ fontWeight: 500, color: "var(--ink-900)" }}>{item.question}</dt>
            <dd style={{ color: "var(--ink-500)", margin: 0 }}>{item.answer}</dd>
          </div>
        ))}
      </dl>
      <FaqLd items={items} />
    </section>
  );
}

export function ArticleLd({
  headline,
  description,
  slug,
  published,
}: {
  headline: string;
  description: string;
  slug: string;
  published: string;
}) {
  const site = process.env.NEXT_PUBLIC_SITE_URL ?? "https://vectorize4u.example";
  const data = {
    "@context": "https://schema.org",
    "@type": "Article",
    headline,
    description,
    datePublished: published,
    dateModified: published,
    mainEntityOfPage: { "@type": "WebPage", "@id": `${site}${slug}` },
    author: { "@type": "Organization", name: "Vectorize4u" },
    publisher: { "@type": "Organization", name: "Vectorize4u" },
  };
  return (
    <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(data) }} />
  );
}
