"use client";

import { useEffect, useState } from "react";

/** A short "how this page works" card for someone new. "Got it" hides it on this browser for good; it only appears
 *  after the page loads, so a seller who dismissed it never sees it flash. */
export function FirstSteps({ id, title, steps }: { id: string; title: string; steps: string[] }) {
  const key = `sal.firststeps.${id}`;
  const [show, setShow] = useState(false);

  useEffect(() => {
    try {
      setShow(localStorage.getItem(key) !== "done");
    } catch {
      setShow(true);   // storage blocked: show it; "Got it" still hides it for this visit
    }
  }, [key]);

  function dismiss() {
    setShow(false);
    try {
      localStorage.setItem(key, "done");
    } catch {
      // nothing to keep; it stays hidden until the page reloads
    }
  }

  if (!show) return null;
  return (
    <section aria-label={title} className="lp-card flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:p-6">
      <div className="flex min-w-0 flex-1 flex-col gap-3">
        <h2 className="text-[16px] font-semibold">{title}</h2>
        <ol className="grid gap-3 sm:grid-cols-3">
          {steps.map((step, i) => (
            <li key={step} className="flex gap-3 text-[15px]">
              <span aria-hidden="true" className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-(--lp-blue) text-[14px] font-semibold text-white">{i + 1}</span>
              <span className="muted">{step}</span>
            </li>
          ))}
        </ol>
      </div>
      <button type="button" onClick={dismiss} className="lp-btn-ghost shrink-0 self-start sm:self-center">Got it</button>
    </section>
  );
}
