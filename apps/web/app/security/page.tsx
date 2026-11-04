import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Security — SAL Resolve",
  description: "How SAL keeps each business's data apart, how sign-in is protected, and why nothing reaches PayPal without you.",
};

// Each point names something the code does today.
const PROTECTIONS = [
  {
    title: "Your data stays yours",
    body: "Every business’s orders, cases and files are separated inside the database itself (PostgreSQL row-level security). If SAL can’t tell which business is asking, the database refuses instead of showing anything.",
  },
  {
    title: "Nothing goes to PayPal without you",
    body: "SAL prepares the reply; you read it, approve it and press send. The approval is tied to the exact documents and case version you saw. If either changes, you review again. A reply with nothing to back it can’t be approved.",
  },
  {
    title: "Sign-in built to resist guessing",
    body: "Passwords are stored only as slow scrypt hashes. You can add a code from an authenticator app, so a stolen password alone opens nothing. Repeated wrong tries lock the account for a while, and sessions end after 30 idle minutes.",
  },
  {
    title: "AI reads, rules decide",
    body: "An AI model reads your documents, but every value it reports must be written on the line it points to, or the box stays blank for you. Whether an invoice matches its order is decided by fixed rules, not by the model.",
  },
  {
    title: "Hidden instructions are ignored",
    body: "Text inside a document or a buyer’s message is treated as text. If it tries to tell SAL what to do, SAL flags it for you and never follows it.",
  },
  {
    title: "A record that can’t be rewritten",
    body: "Approvals and the activity log can only be added to. Nobody, including SAL itself, can edit or delete an entry afterwards.",
  },
  {
    title: "AI agents get their own keys",
    body: "Each buyer or seller agent has its own key with one role. SAL stores only a fingerprint of it, keys expire after 90 days, can be revoked, and repeated wrong keys are slowed down.",
  },
  {
    title: "Proof you can check",
    body: "Packing photos and videos are stored with the time they arrived and a SHA-256 fingerprint, so a changed file can be spotted.",
  },
];



export default function SecurityPage() {
  return (
    <div className="lp sky min-h-screen">
      <header className="border-b border-(--lp-line)">
        <nav aria-label="Main" className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 py-3">
          <Link href="/" className="display text-xl whitespace-nowrap">SAL <span className="muted font-semibold">Resolve</span></Link>
          <span className="flex items-center gap-2">
            <Link href="/" className="lp-btn-ghost hidden sm:inline-flex">Home</Link>
            <Link href="/deals" className="lp-btn">Try Deal Check</Link>
          </span>
        </nav>
      </header>

      <main className="px-4">
        <div className="mx-auto flex max-w-6xl flex-col gap-14 pb-20 pt-12">
          <section className="flex max-w-3xl flex-col gap-4">
            <h1 className="display text-[36px] sm:text-5xl">Security, in plain words</h1>
            <p className="muted text-[18px]">
              SAL handles orders, invoices and dispute evidence, so how it treats them matters. Here is how it
              protects them.
            </p>
          </section>

          <section aria-labelledby="protect" className="flex flex-col gap-6">
            <h2 id="protect" className="text-[24px] font-semibold tracking-tight">How SAL protects your data</h2>
            <ul className="grid gap-px overflow-hidden rounded-[20px] border border-(--lp-line) bg-(--lp-line) sm:grid-cols-2">
              {PROTECTIONS.map((p) => (
                <li key={p.title} className="flex flex-col gap-2 bg-(--lp-card) p-6 sm:p-7">
                  <h3 className="text-[18px] font-semibold">{p.title}</h3>
                  <p className="muted text-[15px] leading-relaxed">{p.body}</p>
                </li>
              ))}
            </ul>
          </section>



        </div>
      </main>

      <footer className="muted mx-auto max-w-6xl border-t border-(--lp-line) px-4 py-6 text-sm">
        © 2026 SAL Resolve · Not affiliated with or endorsed by PayPal.
      </footer>
    </div>
  );
}
