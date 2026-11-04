import Link from "next/link";
import type { ReactNode } from "react";

/** The frame for sign-in, sign-up and the second step: one calm card in the middle of the sky. */
export function AuthShell({ title, lead, children, footer }: { title: string; lead?: string; children: ReactNode; footer?: ReactNode }) {
  return (
    <div className="lp sky flex min-h-screen flex-col">
      <header className="mx-auto flex w-full max-w-6xl items-center justify-between px-4 py-4">
        <Link href="/" className="display text-xl">SAL <span className="muted font-semibold">Resolve</span></Link>
        <Link href="/security" className="muted text-[14px] hover:underline">How SAL keeps your data safe</Link>
      </header>
      <main className="flex flex-1 items-start justify-center px-4 pb-16 pt-8 sm:pt-16">
        <div className="lp-card flex w-full max-w-[420px] flex-col gap-6 p-6 sm:p-8">
          <div className="flex flex-col gap-1.5">
            <h1 className="text-[26px] font-semibold tracking-tight">{title}</h1>
            {lead && <p className="muted text-[15px]">{lead}</p>}
          </div>
          {children}
        </div>
      </main>
      {footer && <p className="muted pb-10 text-center text-[14px]">{footer}</p>}
    </div>
  );
}
