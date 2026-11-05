"use client";

import { useEffect, useState } from "react";

/** Shows that SAL is busy right now: three pulsing dots, the label, and how long it has taken so far. The time counts
 *  from `since` (an ISO time from the server) or from when this appeared. Only real states are shown, never made-up
 *  steps. */
export function Working({ label, since, className = "" }: { label: string; since?: string; className?: string }) {
  const [start] = useState(() => (since ? Date.parse(since) : Date.now()));
  const [now, setNow] = useState(start);
  useEffect(() => {
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  const seconds = Math.max(0, Math.floor((now - start) / 1000));
  return (
    <span role="status" className={`inline-flex items-center gap-2.5 ${className}`}>
      <span aria-hidden="true" className="sal-dots"><span /><span /><span /></span>
      <span>{label}</span>
      <span className="muted tabular-nums">{seconds}s</span>
    </span>
  );
}
