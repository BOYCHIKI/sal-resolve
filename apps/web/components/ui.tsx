import { label } from "@/lib/format";

const tones = {
  neutral: "bg-pearl text-ink-muted ring-hairline",
  info: "bg-info-bg text-info-ink ring-transparent",
  warn: "bg-warn-bg text-warn-ink ring-transparent",
  bad: "bg-bad-bg text-bad-ink ring-transparent",
  good: "bg-good-bg text-good-ink ring-transparent",
};

export type Tone = keyof typeof tones;

export function Badge({ children, tone = "neutral" }: { children: React.ReactNode; tone?: Tone }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${tones[tone]}`}>
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
    <section className="rounded-card border border-hairline bg-surface p-5">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-[17px] text-ink">{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

export function SourceLink({ evidenceId, line }: { evidenceId: string; line: number }) {
  return (
    <a href={`#${evidenceId}-L${line}`} className="font-mono text-xs text-action hover:underline underline-offset-2">
      {evidenceId}:{line}
    </a>
  );
}

/** The single primary action style: Action Blue pill with the press micro-interaction. */
export const primaryButton =
  "inline-flex items-center justify-center rounded-full bg-action px-5 py-2 text-[15px] font-normal text-white " +
  "transition-transform active:scale-95 disabled:cursor-not-allowed disabled:bg-hairline disabled:text-ink-muted disabled:active:scale-100";
