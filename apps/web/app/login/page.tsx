import type { Metadata } from "next";
import Link from "next/link";
import { AuthShell } from "@/components/auth/AuthShell";
import { SignInForm } from "@/components/auth/forms";
import { safeNext } from "@/lib/session";

export const metadata: Metadata = { title: "Sign in — SAL Resolve" };

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ next?: string; expired?: string; signed_out?: string }> }) {
  const { next, expired, signed_out } = await searchParams;
  return (
    <AuthShell title="Sign in" lead="Check deals and answer PayPal disputes for your business."
      footer={<>New to SAL? <Link href="/signup" className="font-semibold text-(--lp-blue) hover:underline">Create an account</Link></>}>
      {expired && <p role="status" className="rounded-xl bg-amber-bg px-4 py-3 text-[14px] text-amber-ink">Your session ended. Sign in again to continue.</p>}
      {signed_out && <p role="status" className="rounded-xl bg-green-bg px-4 py-3 text-[14px] text-green-ink">You are signed out.</p>}
      <SignInForm next={safeNext(next)} />
    </AuthShell>
  );
}
