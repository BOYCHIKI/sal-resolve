import Link from "next/link";

export function AppHeader({ back }: { back?: boolean }) {
  return (
    <header className="glass sticky top-0 z-10 border-x-0 border-t-0">
      <div className="mx-auto flex min-h-[60px] max-w-6xl flex-wrap items-center justify-between gap-3 px-4">
        {back ? (
          <Link href="/disputes" className="inline-flex min-h-11 items-center text-action">‹ All disputes</Link>
        ) : (
          <Link href="/" className="text-lg font-semibold tracking-tight">
            SAL <span className="font-normal text-ink-muted">Resolve</span>
          </Link>
        )}
        <span className="inline-flex items-center gap-2 rounded-full bg-green-bg px-3.5 py-1.5 text-sm text-green-ink">
          <span aria-hidden="true" className="h-2 w-2 rounded-full bg-current" />
          PayPal test mode
        </span>
      </div>
    </header>
  );
}
