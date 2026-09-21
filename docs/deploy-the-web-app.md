# Deploying the web app

The API is on Fly (`docs/deploy-from-github.md`). The site is on Vercel,
for the reason in §2: Vercel functions cannot host a tracer, and they cap
request bodies at about 4.5 MB. Neither matters here, because **uploads
never pass through it** — the browser gets a presigned URL and PUTs the
bytes straight to R2 (§4.3), so a 25 MB logo never touches the site's
host.

Everything below is doable from a phone.

## Once: connect the repository

Vercel builds on push, so there is no token to store and no deploy
workflow to run. In the Vercel dashboard:

1. **Add New → Project**, and pick this repository.
2. **Root Directory: `apps/web`.** This is the one setting that is easy
   to miss and fails confusingly: left at the repository root, the build
   finds no `package.json` it recognises. `apps/web` carries its own
   `package-lock.json` and depends on nothing outside itself, so nothing
   else about the monorepo needs configuring.
3. Framework preset: Next.js. It is detected; confirm rather than change.
4. Leave the build and install commands alone.

## Once: the environment variables

Set all four for **Production**, and the first two for Preview too, or
preview deployments will quietly talk to a different API than the one you
think you are testing.

Two things about the form itself:

- **Type: `Config`, not `Secret`.** Vercel warns about this, and it is
  right. `NEXT_PUBLIC_` means the value is compiled into JavaScript that
  anyone can read in DevTools, so marking it secret claims a privacy the
  prefix has already given away. Every variable below is public by
  nature. The one Supabase value that must never appear here in any form,
  under any type, is the service-role key.
- **No trailing slash on the URLs.** `sitemap.ts` builds `${SITE}/path`,
  so a `NEXT_PUBLIC_SITE_URL` ending in `/` yields `https://host//path`
  for every canonical and every sitemap entry. Those still resolve, which
  is exactly why it survives a glance at the site.

| Variable | Value | Why |
| --- | --- | --- |
| `NEXT_PUBLIC_API_BASE` | `https://vectorize4u-api.fly.dev` | Where the browser sends conversions. |
| `NEXT_PUBLIC_SITE_URL` | your real domain, e.g. `https://vectorize4u.com` | Canonicals, `sitemap.xml`, Open Graph. |
| `NEXT_PUBLIC_SUPABASE_URL` | your Supabase project URL | Sign-in. |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | the **anon** key | Sign-in. |

The last two are the only Supabase values that belong in a browser
bundle. The **service-role key never goes near the web app** — it
bypasses every row-level policy, and `NEXT_PUBLIC_` means "compiled into
JavaScript anyone can read".

Without the Supabase pair the site still works: anonymous previews are
free and rate-limited by IP (§7), which is the landing page's whole
pitch. Sign-in, accounts, unlock and batch need them.

## Why the first two matter more than they look

`next.config.ts` gives both a default — `http://127.0.0.1:8000` and
`https://vectorize.example`. A build that never receives them therefore
**succeeds**. It deploys, renders, and looks right. Then every conversion
in the browser fails against `127.0.0.1`, and the sitemap advertises
`vectorize.example` to Google.

Nothing on the server ever logs that, which is why it gets its own
check rather than a note in a runbook:

```sh
python scripts/verify_site.py https://vectorize4u.com \
    --api https://vectorize4u-api.fly.dev
```

It reads what actually shipped — the home page and the JavaScript bundles
it loads — rather than what the deploy was asked to ship. It also walks
every URL in the sitemap (a sitemap listing a 404 is worse than no
sitemap), checks `robots.txt` points at it, and confirms the API answers
a cross-origin request from the site's origin.

Run it from Actions → **Verify the site** → Run workflow, which is the
same check on a runner, so it needs no terminal.

## Then: the domain

Add it in Vercel under the project's **Domains**, then set
`NEXT_PUBLIC_SITE_URL` to it and redeploy — the canonicals and the
sitemap are baked in at build time, so changing the domain without a
rebuild leaves the old one advertised.

Two things to do in the same sitting:

- Narrow the API's CORS. `apps/api/app/main.py` allows every origin,
  which is right while the only client is a check script and wrong once
  the site is real.
- Point `VEC_CHECKOUT_SUCCESS_URL`, `VEC_CHECKOUT_CANCEL_URL` and
  `VEC_BILLING_PORTAL_RETURN_URL` at the domain before turning payments
  on. The startup check refuses production while they still say
  `localhost`, so this cannot be forgotten silently.
