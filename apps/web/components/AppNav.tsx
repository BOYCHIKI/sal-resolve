"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/deals", label: "Deals", badge: "deals" },
  { href: "/disputes", label: "Disputes", badge: "disputes" },
  { href: "/packing", label: "Packing", badge: null },
] as const;

export type NavCounts = { deals: number; disputes: number };

/** The three areas of SAL. A number means that many things are waiting for the seller. */
export function AppNav({ counts }: { counts: NavCounts }) {
  const path = usePathname();
  return (
    <nav aria-label="Main" className="flex items-center gap-1">
      {LINKS.map(({ href, label, badge }) => {
        const active = path.startsWith(href);
        const waiting = badge ? counts[badge] : 0;
        return (
          <Link key={href} href={href} aria-current={active ? "page" : undefined}
            className={`inline-flex min-h-11 items-center gap-1.5 rounded-full px-3 text-[15px] font-semibold ${active ? "bg-(--lp-card-2)" : "muted"}`}>
            {label}
            {waiting > 0 && (
              <span aria-label={`${waiting} waiting`} className="rounded-full bg-red-bg px-1.5 text-[13px] text-red-ink">{waiting}</span>
            )}
          </Link>
        );
      })}
    </nav>
  );
}
