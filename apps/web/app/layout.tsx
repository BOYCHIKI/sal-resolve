import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "SAL Resolve",
  description: "Reply to PayPal disputes with proof from your own documents. You approve before anything is sent.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <div className="ground-blobs" aria-hidden="true">
          <span style={{ top: -180, left: "8%", width: 640, height: 560, background: "var(--blob-1)" }} />
          <span style={{ top: 140, right: -160, width: 560, height: 520, background: "var(--blob-2)" }} />
          <span style={{ bottom: -200, left: "35%", width: 620, height: 500, background: "var(--blob-3)" }} />
        </div>
        {children}
      </body>
    </html>
  );
}
