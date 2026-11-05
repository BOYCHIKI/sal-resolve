// The seller's session lives in an httpOnly cookie that only this server reads; the browser's scripts never see the
// token. In production the __Host- prefix makes the browser refuse it unless it is Secure, on this host, at path /.
const secure = process.env.NODE_ENV === "production";

export const SESSION_COOKIE = secure ? "__Host-sal_session" : "sal_session";
export const PENDING_COOKIE = secure ? "__Host-sal_pending" : "sal_pending";   // password right, code still owed

export const SESSION_SECONDS = 12 * 60 * 60;   // the API ends a session after 12 hours, or 30 idle minutes
export const PENDING_SECONDS = 5 * 60;

export function cookieOptions(maxAge: number) {
  return { httpOnly: true, secure, sameSite: "lax" as const, path: "/", maxAge };
}

/** Where to go after signing in: only a path on this site, never another host; Home by default. */
export function safeNext(next: string | null | undefined): string {
  return next && next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/\\") ? next : "/home";
}
