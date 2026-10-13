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
      <body className="min-h-screen">
        <header className="sticky top-0 z-10 bg-nav text-on-nav">
          <div className="mx-auto flex h-11 max-w-6xl items-center justify-between px-4 text-xs">
            <Link href="/disputes" className="text-[15px] font-semibold tracking-tight">
              SAL <span className="font-normal opacity-70">Resolve</span>
            </Link>
            <span className="opacity-70">Sandbox demo · no real customer data</span>
          </div>
        </header>
        <main className="mx-auto max-w-6xl px-4 py-8">{children}</main>
      </body>
    </html>
  );
}
