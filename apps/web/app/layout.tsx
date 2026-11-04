import type { Metadata } from "next";
import { Archivo, Inter } from "next/font/google";
import { Motion } from "@/components/motion/Motion";
import "./globals.css";

// Every screen wrapped in .lp (globals.css) reads these; anything outside it keeps the system stack.
const display = Archivo({ subsets: ["latin"], variable: "--font-display", display: "swap" });
const text = Inter({ subsets: ["latin"], variable: "--font-text", display: "swap" });

export const metadata: Metadata = {
  title: "SAL Resolve",
  description: "The deal checker for PayPal sellers worldwide: catch the mistake before delivery, and keep the proof ready. You approve before anything is sent.",
};

// Runs before paint: turn motion on only for visitors who allow it, and give it back if the motion code never loads.
const MOTION_GATE = `(function(){var d=document.documentElement;if(matchMedia("(prefers-reduced-motion: reduce)").matches)return;d.classList.add("motion");setTimeout(function(){if(!window.__salMotion)d.classList.remove("motion")},4000)})()`;

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${display.variable} ${text.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: MOTION_GATE }} />
      </head>
      <body className="min-h-screen">
        <div className="ground-blobs" aria-hidden="true">
          <span style={{ top: -180, left: "8%", width: 640, height: 560, background: "var(--blob-1)" }} />
          <span style={{ top: 140, right: -160, width: 560, height: 520, background: "var(--blob-2)" }} />
          <span style={{ bottom: -200, left: "35%", width: 620, height: 500, background: "var(--blob-3)" }} />
        </div>
        {children}
        <Motion />
      </body>
    </html>
  );
}
