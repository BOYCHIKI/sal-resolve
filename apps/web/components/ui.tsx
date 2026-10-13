import { label } from "@/lib/format";

const tones = {
  neutral: "bg-zinc-100 text-zinc-700 ring-zinc-200 dark:bg-zinc-800 dark:text-zinc-200 dark:ring-zinc-700",
  info: "bg-sky-50 text-sky-800 ring-sky-200 dark:bg-sky-950 dark:text-sky-200 dark:ring-sky-900",
  warn: "bg-amber-50 text-amber-900 ring-amber-200 dark:bg-amber-950 dark:text-amber-200 dark:ring-amber-900",
  bad: "bg-rose-50 text-rose-800 ring-rose-200 dark:bg-rose-950 dark:text-rose-200 dark:ring-rose-900",
  good: "bg-emerald-50 text-emerald-800 ring-emerald-200 dark:bg-emerald-950 dark:text-emerald-200 dark:ring-emerald-900",
};

export type Tone = keyof typeof tones;

export function Badge({ children, tone = "neutral" }: { children: React.ReactNode; tone?: Tone }) {
  return (
    <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${tones[tone]}`}>
      {children}
    </span>
  );
}

export function OriginBadge({ origin }: { origin: string }) {
  return origin === "PAYPAL_SANDBOX" ? <Badge tone="info">PayPal Sandbox</Badge> : <Badge tone="warn">Synthetic fixture</Badge>;
}

export function StateBadge({ state }: { state: string }) {
  const tone: Tone = state === "NEEDS_REVIEW" ? "warn" : state === "APPROVED" ? "good" : state === "FAILED" ? "bad" : "neutral";
  return <Badge tone={tone}>{label(state)}</Badge>;
}

export function Card({ title, children, aside }: { title: string; children: React.ReactNode; aside?: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

export function SourceLink({ evidenceId, line }: { evidenceId: string; line: number }) {
  return (
    <a href={`#${evidenceId}-L${line}`} className="font-mono text-xs text-sky-700 underline-offset-2 hover:underline dark:text-sky-400">
      {evidenceId}:{line}
    </a>
  );
}
