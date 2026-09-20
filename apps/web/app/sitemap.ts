import type { MetadataRoute } from "next";

const SITE = process.env.NEXT_PUBLIC_SITE_URL ?? "https://vectorize.example";

/**
 * §9 — ships in Phase 3. Only the public, indexable pages: /account and
 * the converter's result URLs are private and carry `noindex`.
 */
export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date();
  return [
    { url: `${SITE}/`, lastModified: now, changeFrequency: "weekly", priority: 1 },
    { url: `${SITE}/convert`, lastModified: now, changeFrequency: "weekly", priority: 0.9 },
    { url: `${SITE}/png-to-svg`, lastModified: now, changeFrequency: "weekly", priority: 0.9 },
    {
      url: `${SITE}/convert-for-cricut`,
      lastModified: now,
      changeFrequency: "weekly",
      priority: 0.9,
    },
    { url: `${SITE}/api`, lastModified: now, changeFrequency: "monthly", priority: 0.8 },
    { url: `${SITE}/batch`, lastModified: now, changeFrequency: "monthly", priority: 0.7 },
  ];
}
