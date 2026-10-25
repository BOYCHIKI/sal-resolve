"use client";

import { useRef } from "react";
import { gsap } from "gsap";
import { DrawSVGPlugin } from "gsap/DrawSVGPlugin";
import { useGSAP } from "@gsap/react";

gsap.registerPlugin(DrawSVGPlugin, useGSAP);

/*
 * The landing illustration: three documents are scanned, two check out and one has dates that disagree, the
 * findings flow into SAL, and a reply is drafted that waits for "Approve". The markup is the finished frame, so
 * without motion (or JS) it reads as a still picture; with motion GSAP replays it on a loop while it's on screen.
 */
const DOCS = [
  { x: 40, label: "Invoice", tone: "ok" },
  { x: 190, label: "Payment record", tone: "ok" },
  { x: 340, label: "Delivery", tone: "check" },
] as const;

const ink = { stroke: "var(--ink-muted)" };
const blue = { stroke: "var(--action)" };

export function EvidenceFlow() {
  const root = useRef<SVGSVGElement>(null);

  useGSAP(
    () => {
      if (!document.documentElement.classList.contains("motion")) return;
      const q = gsap.utils.selector(root);
      const tl = gsap.timeline({ repeat: -1, repeatDelay: 1.6, defaults: { ease: "power2.inOut" } });

      tl.set(q(".badge, .flow-dot, .approve-fill, .approve-check"), { autoAlpha: 0 })
        .set(q(".badge"), { scale: 0.4, transformOrigin: "50% 50%" })
        .fromTo(q(".doc-edge"), { drawSVG: "0%" }, { drawSVG: "100%", duration: 0.9, stagger: 0.15 })
        .fromTo(q(".doc-line"), { drawSVG: "0%" }, { drawSVG: "100%", duration: 0.4, stagger: 0.04 }, "-=0.5")
        .fromTo(q(".scan"), { x: 0, autoAlpha: 0 }, { x: 420, autoAlpha: 1, duration: 1.6, ease: "none" })
        .to(q(".scan"), { autoAlpha: 0, duration: 0.2 })
        .to(q(".badge"), { autoAlpha: 1, scale: 1, duration: 0.45, ease: "back.out(2)", stagger: 0.25 }, "-=1.1")
        .fromTo(q(".flow"), { drawSVG: "0%" }, { drawSVG: "100%", duration: 0.8, stagger: 0.12 })
        .fromTo(q(".flow-dot"), { autoAlpha: 0, scale: 0.3, transformOrigin: "50% 50%" }, { autoAlpha: 1, scale: 1, duration: 0.3 }, "-=0.3")
        .fromTo(q(".core-ring"), { scale: 0.85, autoAlpha: 0.2, transformOrigin: "50% 50%" }, { scale: 1.25, autoAlpha: 0, duration: 1, stagger: 0.2, ease: "power1.out" }, "<")
        .fromTo(q(".out"), { drawSVG: "0%" }, { drawSVG: "100%", duration: 0.5 })
        .fromTo(q(".reply-edge"), { drawSVG: "0%" }, { drawSVG: "100%", duration: 0.8 })
        .fromTo(q(".reply-line"), { drawSVG: "0%" }, { drawSVG: "100%", duration: 0.35, stagger: 0.08 }, "-=0.3")
        .fromTo(q(".approve-edge"), { drawSVG: "0%" }, { drawSVG: "100%", duration: 0.5 })
        .to(q(".approve-fill"), { autoAlpha: 1, duration: 0.3 }, "+=0.4")
        .fromTo(q(".approve-check"), { autoAlpha: 0, drawSVG: "0%" }, { autoAlpha: 1, drawSVG: "100%", duration: 0.4 });

      // Only spend frames while the picture is on screen.
      const io = new IntersectionObserver(([e]) => (e.isIntersecting ? tl.play() : tl.pause()));
      if (root.current) io.observe(root.current);
      return () => io.disconnect();
    },
    { scope: root },
  );

  return (
    <svg ref={root} viewBox="0 0 960 300" role="img" className="h-auto w-full"
      aria-label="SAL checks your invoice, payment record and delivery documents, flags the delivery dates that disagree, and drafts a reply for you to approve.">
      <defs>
        <linearGradient id="ef-scan" x1="0" x2="1" y1="0" y2="0">
          <stop offset="0" stopColor="var(--action)" stopOpacity="0" />
          <stop offset="0.8" stopColor="var(--action)" stopOpacity="0.35" />
          <stop offset="1" stopColor="var(--action)" stopOpacity="0.9" />
        </linearGradient>
      </defs>

      <g fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        {DOCS.map((d) => (
          <g key={d.label}>
            <path className="doc-edge" style={ink} d={`M${d.x + 16} 70 h88 l24 24 v136 a12 12 0 0 1 -12 12 h-100 a12 12 0 0 1 -12 -12 v-148 a12 12 0 0 1 12 -12 z`} />
            {[110, 132, 154, 176].map((y, i) => (
              <path key={y} className="doc-line" style={ink} strokeOpacity={0.6} d={`M${d.x + 22} ${y} h${i === 3 ? 48 : 80}`} />
            ))}
            <text x={d.x + 16} y={50} fontSize="15" stroke="none" fill="var(--ink-soft)">{d.label}</text>
            <g className="badge">
              <circle cx={d.x + 118} cy={72} r={14} stroke="none" fill={d.tone === "ok" ? "var(--green-bg)" : "var(--amber-bg)"} />
              {d.tone === "ok" ? (
                <path d={`M${d.x + 112} 72 l4 4 l8 -8`} style={{ stroke: "var(--green-ink)" }} strokeWidth="2.5" />
              ) : (
                <path d={`M${d.x + 118} 65 v8 M${d.x + 118} 79 v0.5`} style={{ stroke: "var(--amber-ink)" }} strokeWidth="2.5" />
              )}
            </g>
          </g>
        ))}

        <rect className="scan" x={20} y={60} width={24} height={196} rx={4} stroke="none" fill="url(#ef-scan)" opacity={0} />

        {[104, 254, 404].map((x, i) => (
          <path key={x} className="flow" style={blue} strokeOpacity={0.7} d={`M${x} 244 C ${x} 290, 560 ${290 - i * 12}, 560 190`} />
        ))}

        <circle className="core-ring" cx={560} cy={150} r={44} style={blue} strokeOpacity={0.5} />
        <circle className="core-ring" cx={560} cy={150} r={44} style={blue} strokeOpacity={0.3} />
        <circle cx={560} cy={150} r={38} stroke="none" fill="var(--action-fill)" />
        <text x={560} y={157} textAnchor="middle" fontSize="20" fontWeight="600" stroke="none" fill="#fff">SAL</text>
        <circle className="flow-dot" cx={560} cy={190} r={5} stroke="none" fill="var(--action)" />

        <path className="out" style={blue} d="M600 150 H650" />
        <path className="out" style={blue} d="M642 142 l8 8 l-8 8" />

        <path className="reply-edge" style={ink} d="M682 70 h236 a14 14 0 0 1 14 14 v120 a14 14 0 0 1 -14 14 h-196 l-28 22 v-22 h-12 a14 14 0 0 1 -14 -14 v-120 a14 14 0 0 1 14 -14 z" />
        {[104, 128, 152].map((y, i) => (
          <path key={y} className="reply-line" style={ink} strokeOpacity={0.6} d={`M700 ${y} h${i === 2 ? 120 : 200}`} />
        ))}
        <rect className="approve-edge" x={820} y={172} width={96} height={32} rx={16} style={blue} />
        <rect className="approve-fill" x={820} y={172} width={96} height={32} rx={16} stroke="none" fill="var(--action-fill)" />
        <text className="approve-fill" x={868} y={193} textAnchor="middle" fontSize="14" fontWeight="500" stroke="none" fill="#fff">Approve</text>
        <path className="approve-check" d="M842 270 l6 6 l12 -12" style={{ stroke: "var(--green-ink)" }} strokeWidth="3" />
        <text x={870} y={276} fontSize="15" stroke="none" fill="var(--ink-soft)">You decide</text>
      </g>
    </svg>
  );
}
