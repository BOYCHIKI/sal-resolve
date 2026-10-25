"use client";

import { usePathname } from "next/navigation";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { SplitText } from "gsap/SplitText";
import { useGSAP } from "@gsap/react";

gsap.registerPlugin(ScrollTrigger, SplitText, useGSAP);

/*
 * One place for page motion, driven by data attributes so server components stay server components:
 *   data-split="hero"    headline lines rise out of a mask and unblur on load
 *   data-split="reveal"  same, when the heading scrolls into view
 *   data-reveal          block fades up into view
 *   data-reveal-stagger  its children fade up one after another
 *   data-tilt            card tilts toward a fine pointer, with a glare (needs a child .glare)
 *   data-highlight       text turns the accent colour while it crosses the middle of the screen
 *   data-count="N"       figure counts up from 0 to N when it scrolls into view
 * It only runs when layout.tsx put .motion on <html>, i.e. the visitor hasn't asked for reduced motion.
 * It re-runs on every route so client-side navigation gets the same treatment.
 */
export function Motion() {
  const pathname = usePathname();

  useGSAP(
    () => {
      (window as { __salMotion?: boolean }).__salMotion = true;
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

      gsap.utils.toArray<HTMLElement>("[data-highlight]").forEach((el) => {
        ScrollTrigger.create({ trigger: el, start: "top 60%", end: "bottom 40%", toggleClass: "is-lit" });
      });

      // Tilt only follows a mouse or trackpad; on touch the cards stay flat.
      if (!window.matchMedia("(hover: hover) and (pointer: fine)").matches) return;
      const cleanups = gsap.utils.toArray<HTMLElement>("[data-tilt]").map((card) => {
        const toX = gsap.quickTo(card, "rotationX", { duration: 0.4, ease: "power2.out" });
        const toY = gsap.quickTo(card, "rotationY", { duration: 0.4, ease: "power2.out" });
        // Set on enter, not once up front: the reveal's clearProps would wipe it.
        const enter = () => gsap.set(card, { transformPerspective: 800, transformOrigin: "center center" });
        const move = (e: PointerEvent) => {
          const b = card.getBoundingClientRect();
          const px = (e.clientX - b.left) / b.width; // 0..1
          const py = (e.clientY - b.top) / b.height;
          toY((0.5 - px) * 2 * 3.5);
          toX((py - 0.5) * 2 * 1.5);
          card.style.setProperty("--gx", `${px * 100}%`);
          card.style.setProperty("--gy", `${py * 100}%`);
        };
        const leave = () => {
          toX(0);
          toY(0);
        };
        card.addEventListener("pointerenter", enter);
        card.addEventListener("pointermove", move);
        card.addEventListener("pointerleave", leave);
        return () => {
          card.removeEventListener("pointerenter", enter);
          card.removeEventListener("pointermove", move);
          card.removeEventListener("pointerleave", leave);
        };
      });
      return () => cleanups.forEach((fn) => fn());
    },
    { dependencies: [pathname], revertOnUpdate: true },
  );

  return null;
}
