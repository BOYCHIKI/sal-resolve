import { Logo } from "@/components/Logo";
import Link from "next/link";
import { signOut } from "@/app/auth-actions";
import { AppNav, type NavCounts } from "@/components/AppNav";
import { api } from "@/lib/api";

async function waitingCounts(): Promise<NavCounts> {
  try {
    const [deals, documents, actions] = await Promise.all([api.listDeals(), api.listDealDocuments(), api.listActions()]);
    return {
      deals: deals.filter((d) => d.status === "HOLD").length + documents.filter((d) => d.status !== "READING").length,
      disputes: actions.filter((a) => a.dispute_id !== null).length,
    };
  } catch {
    return { deals: 0, disputes: 0 };   // the page itself reports an unreachable server
  }
}

// Sits inside a page wrapped in .lp sky (globals.css), so it takes that page's colours.
export async function AppHeader() {
  // The worker syncs PayPal and analyses documents; if it stops, say so instead of letting cases stall silently.
  const [health, counts] = await Promise.all([api.health(), waitingCounts()]);
  const workerDown = !health || health.status !== "ok";
  return (
    <header className="sticky top-0 z-10 border-b border-(--lp-line) bg-(--lp-card) backdrop-blur-xl">
      <div className="mx-auto flex min-h-[60px] max-w-6xl flex-wrap items-center justify-between gap-x-4 gap-y-1 px-4 py-1">
        <Link href="/home" aria-label="SAL Resolve home"><Logo /></Link>
        <div className="order-last w-full sm:order-none sm:mr-auto sm:w-auto">
          <AppNav counts={counts} />
        </div>
        <span className="flex flex-wrap items-center gap-2">
          {workerDown && (
            <span role="status" className="inline-flex items-center gap-2 rounded-full bg-amber-bg px-3.5 py-1.5 text-sm text-amber-ink">
              <span aria-hidden="true" className="h-2 w-2 rounded-full bg-current" />
              {health ? "Background work paused: SAL’s worker isn’t running" : "SAL can’t reach its server"}
            </span>
          )}
          <Link href="/account" className="muted inline-flex min-h-11 items-center px-2 text-[15px] font-semibold hover:text-(--lp-ink)">Account</Link>
          <form action={signOut}>
            <button type="submit" className="muted inline-flex min-h-11 items-center px-2 text-[15px] hover:text-(--lp-ink) hover:underline">Sign out</button>
          </form>
        </span>
      </div>
    </header>
  );
}
