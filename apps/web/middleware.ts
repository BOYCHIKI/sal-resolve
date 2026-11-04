import { NextResponse, type NextRequest } from "next/server";
import { SESSION_COOKIE } from "@/lib/session";

const API_URL = process.env.SAL_API_URL ?? "http://127.0.0.1:8000";

/** Working screens need a live session. The API decides: a missing, ended, idle or forged token sends the seller
 *  to sign in, and the stale cookie is removed. */
export async function middleware(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const toLogin = (expired: boolean) => {
    const url = new URL("/login", request.url);
    url.searchParams.set("next", pathname + search);
    if (expired) url.searchParams.set("expired", "1");
    const res = NextResponse.redirect(url);
    if (expired) res.cookies.delete(SESSION_COOKIE);
    return res;
  };
  const token = request.cookies.get(SESSION_COOKIE)?.value;
  if (!token) return toLogin(false);
  try {
    const res = await fetch(`${API_URL}/api/auth/me`, {
      cache: "no-store",
      headers: {
        "x-sal-session": token,
        ...(process.env.SAL_INTERNAL_TOKEN ? { "x-sal-internal-token": process.env.SAL_INTERNAL_TOKEN } : {}),
      },
    });
    if (res.status === 401) return toLogin(true);
  } catch {
    // The API is down: let the page say so instead of sending the seller to a sign-in that can't work either.
  }
  return NextResponse.next();
}

// Next reads this statically, so it repeats PROTECTED (lib/session.ts) by hand. Keep the two lists the same.
export const config = {
  matcher: ["/deals/:path*", "/disputes/:path*", "/packing/:path*", "/demo/:path*", "/account/:path*"],
};
