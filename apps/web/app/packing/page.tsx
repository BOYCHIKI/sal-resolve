import { AppHeader } from "@/components/AppHeader";
import { PackingFiles } from "@/components/PackingFiles";
import { PackingForm } from "@/components/PackingForm";
import { PageHead } from "@/components/WorkPage";
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
    <li className="flex flex-wrap items-start gap-5 px-5 py-4 sm:px-6">
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
      <AppHeader />
      <main>
        <div className="mx-auto flex max-w-6xl flex-col gap-7 px-4 pb-16 pt-8">
          <PageHead title="Packing proof"
            lead="Photograph or film the item going into the box. If the buyer later says it was wrong or damaged, SAL adds the files to that case. It shows what you packed, not that it was delivered." />

          {error && (
            <p role="alert" className="rounded-[20px] bg-red-bg p-5 text-red-ink">
              SAL can’t reach its server right now. Please try again in a moment.
            </p>
          )}

          <PackingForm />

          {records.length > 0 ? (
            <section aria-label="Packing records" className="flex flex-col gap-3">
              <h2 className="text-[18px] font-semibold">Your packing records <span className="muted font-normal">· {records.length}</span></h2>
              <ul className="lp-card flex flex-col divide-y divide-(--lp-line)">{records.map((p) => <PackingRow key={p.id} p={p} />)}</ul>
            </section>
          ) : !error && (
            <p className="muted lp-dashed rounded-[20px] p-10 text-center">No packing records yet.</p>
          )}
        </div>
      </main>
    </div>
  );
}
