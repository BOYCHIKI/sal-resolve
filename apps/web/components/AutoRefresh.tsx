"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

/** Reloads the page's server data on a timer, so the worker's verdicts appear without a click. It skips a beat while
 *  the tab is hidden or a dialog is open, so nobody's typing or reading is disturbed. */
export function AutoRefresh({ seconds }: { seconds: number }) {
  const router = useRouter();
  useEffect(() => {
    const timer = setInterval(() => {
      if (document.hidden || document.querySelector("dialog[open]")) return;
      router.refresh();
    }, seconds * 1000);
    return () => clearInterval(timer);
  }, [router, seconds]);
  return null;
}
