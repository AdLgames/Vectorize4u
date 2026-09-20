import { createServerClient } from "@supabase/ssr";
import { type NextRequest, NextResponse } from "next/server";

/**
 * Where the magic link lands.
 *
 * Supabase's PKCE flow returns a `code` that has to be exchanged for a
 * session server-side, so the session cookie is set on our own origin
 * rather than left sitting in the URL. A failed exchange sends the user
 * back to sign-in with a reason rather than to a blank page.
 */

export async function GET(request: NextRequest) {
  const { searchParams, origin } = new URL(request.url);
  const code = searchParams.get("code");
  const next = searchParams.get("next") ?? "/account";

  if (!code) {
    const reason = searchParams.get("error_description") ?? "the link was incomplete";
    return NextResponse.redirect(`${origin}/signin?error=${encodeURIComponent(reason)}`);
  }

  const response = NextResponse.redirect(`${origin}${next}`);
  const client = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL ?? "",
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "",
    {
      cookies: {
        getAll: () => request.cookies.getAll(),
        setAll: (cookies) => {
          for (const { name, value, options } of cookies) {
            response.cookies.set(name, value, options);
          }
        },
      },
    },
  );

  const { error } = await client.auth.exchangeCodeForSession(code);
  if (error) {
    return NextResponse.redirect(`${origin}/signin?error=${encodeURIComponent(error.message)}`);
  }
  return response;
}
