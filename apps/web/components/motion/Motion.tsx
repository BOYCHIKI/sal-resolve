"use client";

import { usePathname } from "next/navigation";
import { gsap } from "gsap";
import { MotionPathPlugin } from "gsap/MotionPathPlugin";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { SplitText } from "gsap/SplitText";
import { useGSAP } from "@gsap/react";

gsap.registerPlugin(MotionPathPlugin, ScrollTrigger, SplitText, useGSAP);

/*
 * One place for page motion, driven by data attributes so server components stay server components:
 *   data-split="hero"    headline lines rise out of a mask and unblur on load
 *   data-split="reveal"  same, when the heading scrolls into view
 *   data-reveal          block fades up into view
 *   data-reveal-stagger  its children fade up one after another
 *   data-count="N"       figure counts up from 0 to N when it scrolls into view
 *   data-tilt-in         block leans back and straightens as it scrolls up (the case screen still)
 *   data-orbit           on an <svg>: each .orbit-dot inside rides the path named by its data-path, looping
 *                        (data-seconds per trip, data-start as a head start, data-reverse to go the other way);
 *                        data-orbit-origin="x y" also widens the svg's own paths out from that point on load
 *   data-nav             landing header folds into a floating pill once the page scrolls (globals.css, .is-stuck)
 * data-nav is a state change rather than motion, so it runs for everyone; the rest only runs when layout.tsx put
 * .motion on <html>, i.e. the visitor hasn't asked for reduced motion.
 * It re-runs on every route so client-side navigation gets the same treatment.
 */
export function Motion() {
  const pathname = usePathname();

  useGSAP(
    () => {
      (window as { __salMotion?: boolean }).__salMotion = true;
      gsap.utils.toArray<HTMLElement>("[data-nav]").forEach((el) => {
        ScrollTrigger.create({ start: 80, end: "max", toggleClass: { targets: el, className: "is-stuck" } });
      });
      if (!document.documentElement.classList.contains("motion")) return;

      const lineTween = (lines: Element[], extra: gsap.TweenVars) =>
        gsap.fromTo(
          lines,
          { yPercent: 100, autoAlpha: 0, filter: "blur(15px)" },
          { yPercent: 0, autoAlpha: 1, filter: "blur(0px)", duration: 1.2, ease: "power3.out", stagger: 0.06, clearProps: "filter", ...extra },
        );

      gsap.utils.toArray<HTMLElement>("[data-split]").forEach((el) => {
        const onScroll = el.dataset.split === "reveal";
        gsap.set(el, { autoAlpha: 1 });
        SplitText.create(el, {
          type: "lines",
          mask: "lines",
          linesClass: "split-line",
          autoSplit: true,
          onSplit: (self) =>
            lineTween(self.lines, onScroll ? { scrollTrigger: { trigger: el, start: "top 85%", once: true } } : { delay: 0.15 }),
        });
      });

      const rise = { y: "2.5rem", autoAlpha: 0 };
      // clearProps hands transform back to CSS afterwards, so classes like active:scale-[0.99] keep working.
      const risen = { y: 0, autoAlpha: 1, duration: 0.6, ease: "power1.out", clearProps: "transform" };
      gsap.utils.toArray<HTMLElement>("[data-reveal]").forEach((el) => {
        gsap.fromTo(el, rise, { ...risen, scrollTrigger: { trigger: el, start: "top 92%", once: true } });
      });
      gsap.utils.toArray<HTMLElement>("[data-reveal-stagger]").forEach((el) => {
        gsap.fromTo(el.children, rise, { ...risen, stagger: 0.08, scrollTrigger: { trigger: el, start: "top 92%", once: true } });
      });

      gsap.utils.toArray<HTMLElement>("[data-tilt-in]").forEach((el) => {
        gsap.fromTo(el, { rotateX: 14, scale: 0.93, y: 40, transformPerspective: 1400, transformOrigin: "50% 0%" }, {
          rotateX: 0, scale: 1, y: 0, ease: "none",
          scrollTrigger: { trigger: el, start: "top bottom", end: "top 20%", scrub: true },
        });
      });

      gsap.utils.toArray<SVGSVGElement>("[data-orbit]").forEach((svg) => {
        const origin = svg.dataset.orbitOrigin;
        if (origin) {
          gsap.fromTo(svg.querySelectorAll(":scope > path"), { autoAlpha: 0, scale: 0.86 },
            { autoAlpha: 1, scale: 1, svgOrigin: origin, duration: 1.6, ease: "power3.out", stagger: 0.12 });
        }
        svg.querySelectorAll<SVGGElement>(".orbit-dot").forEach((dot) => {
          const path = svg.querySelector<SVGPathElement>(dot.dataset.path ?? "");
          if (!path) return;
          const back = dot.dataset.reverse !== undefined;
          gsap.to(dot, {
            motionPath: { path, align: path, alignOrigin: [0.5, 0.5], start: back ? 1 : 0, end: back ? 0 : 1 },
            duration: Number(dot.dataset.seconds ?? 40), ease: "none", repeat: -1,
          }).progress(Number(dot.dataset.start ?? 0));
        });
      });

      // The server already rendered the final number, so without motion the figure is simply there.
      gsap.utils.toArray<HTMLElement>("[data-count]").forEach((el) => {
        const end = Number(el.dataset.count);
        const n = { v: 0 };
        el.textContent = "0";
        gsap.to(n, {
          v: end, duration: 1.4, ease: "power2.out",
          onUpdate: () => { el.textContent = String(Math.round(n.v)); },
          scrollTrigger: { trigger: el, start: "top 90%", once: true },
        });
      });
    },
    { dependencies: [pathname], revertOnUpdate: true },
  );

  return null;
}
