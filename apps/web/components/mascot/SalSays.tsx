/*
 * SAL speaking: the mascot on its cloud with a glass speech bubble beside it (globals.css, .speech and .mascot-cloud).
 * Stacks on phones with the bubble's tail pointing up at SAL; side by side from lg with the tail pointing left.
 * Landing and /demo only; the merchant pages stay mascot-free.
 */
export function SalSays({ mascot, children, className = "", bubbleClassName = "", reveal = true }: {
  mascot: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  bubbleClassName?: string;
  reveal?: boolean; // fade up on scroll (Motion.tsx, data-reveal); the hero runs its own entrance instead
}) {
  return (
    <div data-reveal={reveal || undefined} className={`flex flex-col items-center gap-3 lg:flex-row lg:gap-8 ${className}`}>
      <span className="mascot-cloud relative shrink-0">{mascot}</span>
      <div className={`speech lp-card relative text-left ${bubbleClassName}`}>{children}</div>
    </div>
  );
}
