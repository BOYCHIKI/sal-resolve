/*
 * A still of SAL's own case screen (app/disputes/[id]), drawn in HTML for the landing. Labels follow the real
 * screen and the practice case; nothing here is interactive.
 */
const FACTS = [
  { label: "Amount paid", value: "130.41 USD", source: "PayPal record", ok: true },
  { label: "Tracking number", value: "TRK-SYN-72140", source: "Courier slip", ok: true },
  { label: "Courier", value: "JNE → IDN_JNE", source: "Courier slip", ok: true },
  { label: "Delivered on", value: "19 Aug or 20 Aug?", source: "Slip vs receipt", ok: false },
];

export function CaseMockup() {
  return (
    <div className="mock" aria-label="SAL case screen, practice case" role="img">
      <div className="flex items-center justify-between border-b border-[#e6e8ee] px-5 py-3">
        <span className="text-[13px] font-semibold text-[#0b0c0f]">SAL <span className="font-normal text-[#6b7180]">Resolve</span></span>
        <span className="flex items-center gap-1.5 rounded-full bg-[#e7f6ec] px-2.5 py-1 text-[11px] font-medium text-[#1d6b37]">
          <span className="h-1.5 w-1.5 rounded-full bg-current" />PayPal test mode
        </span>
      </div>

      <div className="grid gap-5 p-5 md:grid-cols-[1.25fr_1fr] md:p-7">
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-[11px] text-[#6b7180]">Item not received · Order 72140 · Practice case</p>
              <p className="text-[19px] font-semibold tracking-tight text-[#0b0c0f]">Wireless Keyboard</p>
            </div>
            <p className="text-right text-[19px] font-semibold tabular-nums text-[#0b0c0f]">130.41 USD</p>
          </div>
          <div className="flex flex-wrap gap-2 text-[11px] font-medium">
            <span className="rounded-full bg-[#fff4d6] px-2.5 py-1 text-[#5c3d00]">Check 1 detail first</span>
            <span className="rounded-full bg-[#eef1f6] px-2.5 py-1 text-[#424245]">Reply by 3 Sep · 9 days left</span>
          </div>

          <div className="rounded-xl border border-[#e6e8ee]">
            <p className="border-b border-[#e6e8ee] px-4 py-2.5 text-[12px] font-semibold text-[#0b0c0f]">What your documents show</p>
            <ul>
              {FACTS.map((f) => (
                <li key={f.label} className={`grid grid-cols-[1fr_auto] items-center gap-x-3 border-b border-[#eef0f4] px-4 py-2.5 last:border-0 ${f.ok ? "" : "bg-[#fffaeb]"}`}>
                  <span className="text-[11px] text-[#6b7180]">{f.label}</span>
                  <span className={`row-span-2 rounded-md px-2 py-0.5 text-[10px] font-medium ${f.ok ? "bg-[#e7f6ec] text-[#1d6b37]" : "bg-[#fff1c7] text-[#7a5200]"}`}>
                    {f.ok ? "Proven" : "Please check"}
                  </span>
                  <span className="truncate text-[13px] font-medium text-[#0b0c0f]">
                    {f.value} <span className="font-normal text-[#9097a3]">· {f.source}</span>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </div>

        <div className="hidden flex-col gap-3 rounded-xl bg-[#f5f7fa] p-5 md:flex">
          <p className="text-[12px] font-semibold text-[#0b0c0f]">Your reply to PayPal</p>
          <p className="text-[11px] text-[#6b7180]">Written by SAL from your documents</p>
          <p className="text-[13px] leading-relaxed text-[#26282e]">
            The customer paid <mark className="mock-fact">130.41 USD</mark> for this order. We shipped it with{" "}
            <mark className="mock-fact">JNE</mark>, tracking number <mark className="mock-fact">TRK-SYN-72140</mark>. The parcel was
            delivered on <mark className="mock-gap">date to confirm</mark>.
          </p>
          <p className="mt-auto text-[11px] text-[#6b7180]">The delivery date will be added once you confirm it above.</p>
          <span className="self-start rounded-full bg-[#d9dde5] px-4 py-2 text-[12px] font-semibold text-[#6b7180]">Approve reply</span>
        </div>
      </div>
    </div>
  );
}
