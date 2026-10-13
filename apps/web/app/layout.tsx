import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "SAL Resolve",
  description: "Evidence-grounded PayPal dispute responses, prepared by an agent and approved by you.",
  robots: { index: false, follow: false }, // app pages are private; noindex is not a security control
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-zinc-50 text-zinc-900 antialiased dark:bg-zinc-950 dark:text-zinc-100">
        <header className="border-b border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
          <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
            <Link href="/disputes" className="text-base font-semibold tracking-tight">
              SAL <span className="font-normal text-zinc-500">Resolve</span>
            </Link>
            <span className="text-xs text-zinc-500">Sandbox demo · no real customer data</span>
          </div>
        </header>
        <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
      </body>
    </html>
  );
}
