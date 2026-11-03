/*
 * A still of SAL's Deal Check screen (app/deals), drawn in HTML for the landing. The deal is invented, and its numbers
 * follow the service case in app/simulate_agents.py. Nothing here is interactive.
 */
const DIFFERENCES = [
  { label: "Quantity", ordered: "10 hours", invoiced: "12 hours" },
  { label: "Total", ordered: "800.00 USD", invoiced: "960.00 USD" },
];

export function CaseMockup() {
  return (
    <div className="mock" aria-label="SAL Deal Check screen, an invented deal held before delivery" role="img">
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
              <p className="text-[11px] text-[#6b7180]">Service · Order PO-4411 · Example</p>
              <p className="text-[19px] font-semibold tracking-tight text-[#0b0c0f]">Website audit</p>
            </div>
            <span className="rounded-full bg-[#fde8e6] px-2.5 py-1 text-[11px] font-semibold text-[#a3241b]">Don’t deliver yet</span>
          </div>

          <div className="rounded-xl border border-[#e6e8ee]">
            <div className="grid grid-cols-3 gap-2 border-b border-[#e6e8ee] px-4 py-2.5 text-[11px] font-semibold text-[#6b7180]">
              <span>What differs</span><span>Ordered</span><span>Invoiced</span>
            </div>
            <ul>
              {DIFFERENCES.map((d) => (
                <li key={d.label} className="grid grid-cols-3 gap-2 border-b border-[#eef0f4] bg-[#fffaeb] px-4 py-2.5 text-[12px] last:border-0">
                  <span className="font-semibold text-[#0b0c0f]">{d.label}</span>
                  <span className="text-[#26282e]">{d.ordered}</span>
                  <span className="font-medium text-[#a3241b]">{d.invoiced}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>

        <div className="hidden flex-col gap-3 rounded-xl bg-[#f5f7fa] p-5 md:flex">
          <p className="text-[12px] font-semibold text-[#0b0c0f]">Your correction request</p>
          <p className="text-[11px] text-[#6b7180]">Written by SAL from the differences</p>
          <p className="text-[13px] leading-relaxed text-[#26282e]">
            Order PO-4411 and invoice INV-4411 do not match. Ordered <mark className="mock-fact">800.00 USD</mark>, invoiced{" "}
            <mark className="mock-gap">960.00 USD</mark>. Please send a corrected document.
          </p>
          <p className="mt-auto text-[11px] text-[#6b7180]">You send it. Nothing goes to PayPal.</p>
          <span className="self-start rounded-full bg-[#d9dde5] px-4 py-2 text-[12px] font-semibold text-[#6b7180]">Copy message</span>
        </div>
      </div>
    </div>
  );
}
