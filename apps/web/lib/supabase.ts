"use client";

import type { SupabaseClient } from "@supabase/supabase-js";

/**
 * The browser Supabase client, **loaded on demand**.
 *
 * The auth provider sits in the root layout, so a static import here would
 * put the whole Supabase SDK into the first-load bundle of every page —
 * including `/png-to-svg` and `/convert-for-cricut`, which exist to be
 * indexed and carry a Core Web Vitals budget (§9). It measured at +72 kB.
 * A visitor who never signs in never downloads it.
 *
 * Only the **anon** key belongs in the browser. It is public by design; the
 * service-role key never comes near this app, because every privileged
 * action goes through `/v1`, which verifies the session token itself.
 */

const URL = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
const ANON_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "";

export const supabaseConfigured = Boolean(URL && ANON_KEY);

let client: SupabaseClient | null = null;
let loading: Promise<SupabaseClient> | null = null;

export async function supabase(): Promise<SupabaseClient> {
  if (!supabaseConfigured) {
    throw new Error("Supabase is not configured");
  }
  if (client) return client;
  // One client per tab: each instance registers its own auth listener and
  // its own refresh timer. The in-flight promise is shared so two callers
  // during startup do not create two.
  loading ??= import("@supabase/ssr").then(({ createBrowserClient }) => {
    client = createBrowserClient(URL, ANON_KEY);
    return client;
  });
  return loading;
}
