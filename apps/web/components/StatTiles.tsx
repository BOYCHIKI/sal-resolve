import type { ReactNode } from "react";

export type Stat = { label: string; value: ReactNode; note?: string; tone?: "red" | "amber" | "blue" | "green"; icon: ReactNode };

const TINT = {
  red: "bg-red-bg text-red-ink",
  amber: "bg-amber-bg text-amber-ink",
  blue: "bg-blue-bg text-blue-ink",
  green: "bg-green-bg text-green-ink",
};

/** The row of figures at the top of a working screen: what is waiting, at a glance. */
export function StatTiles({ stats }: { stats: Stat[] }) {
  return (
    <ul className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {stats.map((s) => (
        <li key={s.label} className="lp-card flex flex-col gap-3 p-4 sm:p-5">
          <span className="flex items-center gap-2.5">
            <span aria-hidden="true" className={`grid h-8 w-8 place-items-center rounded-lg ${TINT[s.tone ?? "blue"]}`}>
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"
                strokeLinejoin="round">{s.icon}</svg>
            </span>
            <span className="muted text-[14px] font-medium">{s.label}</span>
          </span>
          <span className="text-[26px] font-semibold leading-none tabular-nums sm:text-[30px]">{s.value}</span>
          {s.note && <span className="muted text-[13px]">{s.note}</span>}
        </li>
      ))}
    </ul>
  );
}

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

export const ICONS = {
  alert: <><circle cx="12" cy="12" r="9" /><path d="M12 8v4M12 16h.01" /></>,
  clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
  check: <><circle cx="12" cy="12" r="9" /><path d="M8 12l3 3 5-6" /></>,
  file: <><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" /><path d="M14 3v6h6" /></>,
  lock: <><rect x="5" y="11" width="14" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></>,
  cases: <><rect x="3" y="7" width="18" height="13" rx="2" /><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /></>,
  spin: <><path d="M21 12a9 9 0 1 1-3-6.7" /><path d="M21 4v5h-5" /></>,
};
