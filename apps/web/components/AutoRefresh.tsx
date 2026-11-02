"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

/** Reloads the page's server data on a timer, so the worker's verdicts appear without a click. */
export function AutoRefresh({ seconds }: { seconds: number }) {
  const router = useRouter();
  useEffect(() => {
    const timer = setInterval(() => router.refresh(), seconds * 1000);
    return () => clearInterval(timer);
  }, [router, seconds]);
  return null;
}
