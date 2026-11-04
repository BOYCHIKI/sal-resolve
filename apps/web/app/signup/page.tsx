import type { Metadata } from "next";
import Link from "next/link";
import { AuthShell } from "@/components/auth/AuthShell";
import { SignUpForm } from "@/components/auth/forms";

export const metadata: Metadata = { title: "Create an account — SAL Resolve" };

export default function SignUpPage() {
  return (
    <AuthShell title="Create an account" lead="One account per business. You can turn on two-step sign-in right after."
      footer={<>Already have an account? <Link href="/login" className="font-semibold text-(--lp-blue) hover:underline">Sign in</Link></>}>
      <SignUpForm />
    </AuthShell>
  );
}
