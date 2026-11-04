import type { Metadata } from "next";
import { AppHeader } from "@/components/AppHeader";
import { ChangePasswordForm, SignOutOthersButton, TwoStepOff, TwoStepSetup } from "@/components/auth/forms";
import { PageHead } from "@/components/WorkPage";
import { auth } from "@/lib/api";

export const metadata: Metadata = { title: "Account and security — SAL Resolve" };
export const dynamic = "force-dynamic";

function when(iso: string): string {
  return new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

// "Chrome on Windows" from a user-agent string; good enough to recognise your own devices.
function device(ua: string | null): string {
  if (!ua) return "Unknown device";
  const browser = /Edg\//.test(ua) ? "Edge" : /Chrome\//.test(ua) ? "Chrome" : /Firefox\//.test(ua) ? "Firefox" : /Safari\//.test(ua) ? "Safari" : "Browser";
  const os = /Windows/.test(ua) ? "Windows" : /Android/.test(ua) ? "Android" : /iPhone|iPad/.test(ua) ? "iPhone or iPad" : /Mac OS/.test(ua) ? "Mac" : /Linux/.test(ua) ? "Linux" : "";
  return os ? `${browser} on ${os}` : browser;
}

function Section({ title, lead, children }: { title: string; lead?: string; children: React.ReactNode }) {
  return (
    <section className="lp-card grid gap-5 p-6 sm:p-7 md:grid-cols-[260px_1fr] md:gap-10">
      <div className="flex flex-col gap-1">
        <h2 className="text-[18px] font-semibold">{title}</h2>
        {lead && <p className="muted text-[14px]">{lead}</p>}
      </div>
      <div className="flex min-w-0 flex-col gap-4">{children}</div>
    </section>
  );
}

export default async function AccountPage({ searchParams }: { searchParams: Promise<{ welcome?: string }> }) {
  const { welcome } = await searchParams;
  const me = await auth.me().catch(() => null);
  return (
    <div className="lp sky min-h-screen">
      <AppHeader />
      <main>
        <div className="mx-auto flex max-w-6xl flex-col gap-6 px-4 pb-16 pt-8">
          <PageHead title="Account and security" lead="Who you are signed in as, and how your account is protected." />
          {!me ? (
            <p role="alert" className="rounded-[20px] bg-red-bg p-5 text-red-ink">SAL can’t reach its server right now. Please try again in a moment.</p>
          ) : (
            <>
              {welcome && !me.totp_enabled && (
                <p role="status" className="rounded-[20px] bg-blue-bg px-5 py-4 text-[15px] text-blue-ink">
                  Your account is ready. Turn on two-step sign-in below: it stops anyone who learns your password.
                </p>
              )}
              <Section title="Signed in as">
                <dl className="grid gap-x-6 gap-y-1 text-[15px] sm:grid-cols-[120px_1fr]">
                  <dt className="muted">Email</dt><dd className="font-medium [overflow-wrap:anywhere]">{me.email}</dd>
                  <dt className="muted">Business</dt><dd className="font-medium">{me.business}</dd>
                </dl>
              </Section>

              <Section title="Two-step sign-in"
                lead="After your password, SAL asks for a code from an app on your phone. A stolen password alone won’t open your account.">
                {me.totp_enabled ? (
                  <>
                    <p className="text-[15px]"><span className="font-semibold">On.</span>{" "}
                      <span className="muted">{me.recovery_codes_left} of 10 recovery codes left.</span></p>
                    <TwoStepOff />
                  </>
                ) : (
                  <>
                    <p className="text-[15px]"><span className="font-semibold">Off.</span> <span className="muted">Only your password protects this account.</span></p>
                    <TwoStepSetup />
                  </>
                )}
              </Section>

              <Section title="Password" lead="Changing it signs out every other session.">
                <ChangePasswordForm />
              </Section>

              <Section title="Where you’re signed in" lead="A session ends after 30 minutes without use, and after 12 hours at most.">
                <ul className="flex flex-col divide-y divide-(--lp-line) rounded-xl border border-(--lp-line)">
                  {me.sessions.map((s) => (
                    <li key={s.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 text-[15px]">
                      <span className="font-medium">{device(s.user_agent)}{s.this_one && <span className="muted font-normal"> · this browser</span>}</span>
                      <span className="muted text-[14px]">Signed in {when(s.signed_in_at)} · last active {when(s.last_seen_at)}</span>
                    </li>
                  ))}
                </ul>
                {me.sessions.length > 1 && <SignOutOthersButton />}
              </Section>
            </>
          )}
        </div>
      </main>
    </div>
  );
}
