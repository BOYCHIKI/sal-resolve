import type { Metadata } from "next";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { AuthShell } from "@/components/auth/AuthShell";
import { VerifyForm } from "@/components/auth/forms";
import { PENDING_COOKIE, safeNext } from "@/lib/session";

export const metadata: Metadata = { title: "Two-step sign-in — SAL Resolve" };

export default async function VerifyPage({ searchParams }: { searchParams: Promise<{ next?: string }> }) {
  if (!(await cookies()).get(PENDING_COOKIE)) redirect("/login?expired=1");
  const { next } = await searchParams;
  return (
    <AuthShell title="Enter your code" lead="Open your authenticator app and type the 6-digit code for SAL Resolve. You have 5 minutes.">
      <VerifyForm next={safeNext(next)} />
    </AuthShell>
  );
}
