/* Small pieces shared by the landing pages (app/page.tsx, app/demo/page.tsx). */
export const Check = () => (
  <svg aria-hidden="true" className="mt-1 shrink-0" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--lp-mint)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12l5 5L20 7" /></svg>
);

export const Label = ({ children }: { children: React.ReactNode }) => (
  <span className="lp-label"><span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-(--lp-mint)" />{children}</span>
);
