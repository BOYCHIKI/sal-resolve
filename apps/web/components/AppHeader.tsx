import Link from "next/link";
import { api } from "@/lib/api";

// Sits inside a page wrapped in .lp (globals.css), so it takes the landing look.
export async function AppHeader({ back }: { back?: boolean }) {
  // The worker syncs PayPal and analyses documents; if it stops, say so instead of letting cases stall silently.
  const health = await api.health();
  const workerDown = !health || health.status !== "ok";
  return (
    <header className="sticky top-0 z-10 border-b border-(--lp-line) bg-(--lp-card) backdrop-blur-xl">
      <div className="mx-auto flex min-h-[60px] max-w-6xl flex-wrap items-center justify-between gap-3 px-4">
        {back ? (
          <Link href="/disputes" className="inline-flex min-h-11 items-center text-[15px] font-semibold">‹ All disputes</Link>
        ) : (
          <Link href="/" className="display text-xl">
            SAL <span className="muted font-semibold">Resolve</span>
          </Link>
        )}
        <span className="flex flex-wrap items-center gap-2">
          {workerDown && (
            <span role="status" className="inline-flex items-center gap-2 rounded-full bg-amber-bg px-3.5 py-1.5 text-sm text-amber-ink">
              <span aria-hidden="true" className="h-2 w-2 rounded-full bg-current" />
              {health ? "Background work paused: SAL’s worker isn’t running" : "SAL can’t reach its server"}
            </span>
          )}
          <span className="inline-flex items-center gap-2 rounded-full bg-green-bg px-3.5 py-1.5 text-sm text-green-ink">
            <span aria-hidden="true" className="h-2 w-2 rounded-full bg-current" />
            PayPal test mode
          </span>
        </span>
      </div>
    </header>
  );
}
