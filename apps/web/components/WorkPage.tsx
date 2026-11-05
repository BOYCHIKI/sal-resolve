import Link from "next/link";
import type { ReactNode } from "react";

/** A short page title with one line under it, and the page's main action on the right. */
export function PageHead({ title, lead, children }: { title: string; lead: string; children?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div className="flex max-w-2xl flex-col gap-1.5">
        <h1 className="text-[28px] font-semibold tracking-tight sm:text-[32px]">{title}</h1>
        <p className="muted text-[16px]">{lead}</p>
      </div>
      {children}
    </div>
  );
}

/** `alert` marks the tab that needs action now: its count turns red while it has anything in it. */
export type View = { key: string; label: string; count: number; alert?: boolean };

/** One kind of work per tab, so documents to confirm, held deals and finished ones never share a list. The tab is in
 *  the address (?view=), so the page stays a server page and a link can open the right tab. */
export function ViewTabs({ views, current, path }: { views: View[]; current: string; path: string }) {
  return (
    <nav aria-label="Views" className="-mx-4 overflow-x-auto px-4">
      <ul className="flex min-w-max gap-6 border-b border-(--lp-line)">
        {views.map((v) => {
          const active = v.key === current;
          return (
            <li key={v.key}>
              <Link href={`${path}?view=${v.key}`} aria-current={active ? "page" : undefined} scroll={false}
                className={`-mb-px inline-flex min-h-11 items-center gap-2 border-b-2 text-[15px] font-semibold ${active ? "border-(--lp-blue)" : "muted border-transparent hover:text-(--lp-ink)"}`}>
                {v.label}
                <span className={`rounded-full px-2 text-[13px] tabular-nums ${v.alert && v.count ? "bg-red-ink text-white"
                  : active ? "bg-(--lp-ink) text-white" : "bg-(--lp-card-2)"}`}>{v.count}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

/** The tab asked for; otherwise one that needs action now; otherwise the first with something in it. */
export function pickView(views: View[], asked: string | undefined): string {
  if (asked && views.some((v) => v.key === asked)) return asked;
  return (views.find((v) => v.alert && v.count > 0) ?? views.find((v) => v.count > 0) ?? views[0]).key;
}

/** One sentence that says what this tab is for, above its list. */
export function ViewLead({ children }: { children: ReactNode }) {
  return <p className="muted -mt-2 text-[15px]">{children}</p>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="muted rounded-[20px] border border-dashed border-(--lp-line-strong) p-10 text-center">{children}</p>;
}
