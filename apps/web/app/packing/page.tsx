import { AppHeader } from "@/components/AppHeader";
import { Label } from "@/components/landing/Label";
import { PackingFiles } from "@/components/PackingFiles";
import { PackingForm } from "@/components/PackingForm";
import { api, type PackingRecord } from "@/lib/api";

export const dynamic = "force-dynamic";

function when(iso: string): string {
  return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

function PackingRow({ p }: { p: PackingRecord }) {
  const photos = p.files.filter((f) => f.mime.startsWith("image/")).length;
  const videos = p.files.length - photos;
  const refs = [p.order_ref && `Order ${p.order_ref}`, p.transaction_id && `PayPal ${p.transaction_id}`,
    p.tracking_number && `Resi ${p.tracking_number}`].filter(Boolean).join(" · ");
  return (
    <li className="lp-card flex flex-wrap items-start gap-5 px-6 py-5">
      <div className="flex min-w-0 flex-[999_1_280px] flex-col gap-1">
        <span className="text-[17px] font-semibold">{refs}</span>
        <span className="muted text-[15px]">
          Recorded {when(p.created_at)} · {photos} photo{photos === 1 ? "" : "s"}, {videos} video{videos === 1 ? "" : "s"} · kept until {when(p.expires_at)}
        </span>
        <span className="muted font-mono text-[13px]">Code {p.code.match(/.{1,4}/g)?.join(" ")}</span>
      </div>
      <div className="flex flex-[1_1_220px] flex-col gap-2">
        <PackingFiles packingId={p.id} />
        <a href={`/packing/${p.id}/label`} className="text-center text-[15px] font-semibold underline underline-offset-4">
          Download QR label
        </a>
      </div>
    </li>
  );
}

export default async function PackingPage() {
  let records: PackingRecord[] = [];
  let error = false;
  try {
    records = await api.listPacking();
  } catch {
    error = true;
  }

  return (
    <div className="lp sky min-h-screen">
      <AppHeader back />
      <main className="relative">
        <div aria-hidden="true" className="lp-dots absolute inset-x-0 top-0 h-80" />
        <div className="relative mx-auto flex max-w-6xl flex-col gap-8 px-4 pb-16 pt-12">
          <div className="flex flex-col items-start gap-4">
            <Label>Before you ship</Label>
            <h1 className="display text-[42px] sm:text-6xl">Packing proof</h1>
            <p className="muted max-w-2xl text-[17px]">
              Film or photograph the item going into the box. SAL keeps the files with the time they arrived and a
              fingerprint of each one. If the buyer later says the item was wrong or damaged, SAL adds the photos to
              that case for you. It shows what you packed, not that it was delivered.
            </p>
          </div>

          {error && (
            <p role="alert" className="rounded-[20px] bg-red-bg p-5 text-red-ink">
              SAL can’t reach its server right now. Please try again in a moment.
            </p>
          )}

          <PackingForm />

          {records.length > 0 ? (
            <section aria-label="Packing records" className="flex flex-col gap-3">
              <h2 className="text-xl font-semibold">Your packing records <span className="muted">· {records.length}</span></h2>
              <ul className="flex flex-col gap-2.5">{records.map((p) => <PackingRow key={p.id} p={p} />)}</ul>
            </section>
          ) : !error && (
            <p className="muted lp-dashed rounded-[20px] p-10 text-center">No packing records yet.</p>
          )}
        </div>
      </main>
    </div>
  );
}
