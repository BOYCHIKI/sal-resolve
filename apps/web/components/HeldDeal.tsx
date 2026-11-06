import { DealDocumentUpload } from "@/components/DealDocumentUpload";
import { PayPalInvoiceCheck } from "@/components/PayPalInvoiceCheck";
import { RequestCorrection } from "@/components/RequestCorrection";
import type { Deal, DealFinding, DealFindingCode } from "@/lib/api";
import { amount } from "@/lib/format";
import { date } from "@/lib/plain";

type Explained = { title: string; body: string; fix: string };

/** Each kind of difference in the seller's words: what is wrong, and the two ways to settle it. */
function explain(f: DealFinding, currency: string): Explained {
  const money = (v: string | null) => amount(v, currency);
  const item = f.field;
  const table: Record<DealFindingCode, () => Explained> = {
    QUANTITY_DIFFERS: () => ({ title: `Quantity of ${item}`, body: `The order asks for ${f.ordered}; the invoice says ${f.invoiced}.`,
      fix: `Invoice ${f.ordered}, or get the buyer’s written OK for ${f.invoiced}.` }),
    UNIT_PRICE_DIFFERS: () => ({ title: `Price of ${item}`, body: `Agreed at ${money(f.ordered)} each; invoiced at ${money(f.invoiced)}.`,
      fix: "Use the agreed price, or get the buyer’s OK for the new one." }),
    ITEM_NOT_ORDERED: () => ({ title: `${item} isn’t on the order`, body: "The invoice charges for an item the buyer didn’t order.",
      fix: "Remove it from the invoice, or ask the buyer to add it to the order." }),
    ITEM_NOT_INVOICED: () => ({ title: `${item} is missing from the invoice`, body: "The buyer ordered it, but the invoice doesn’t include it.",
      fix: "Add it to the invoice, or agree with the buyer that it won’t be delivered." }),
    TOTAL_DOES_NOT_ADD_UP: () => ({ title: "The total doesn’t add up",
      body: `Items, shipping and tax come to ${money(f.ordered)}; the invoice total says ${money(f.invoiced)}.`,
      fix: "Correct the total, or the line that’s wrong." }),
    OVER_APPROVED_LIMIT: () => ({ title: "Over what the buyer approved",
      body: `The buyer approved up to ${money(f.ordered)}; the invoice is ${money(f.invoiced)}.`,
      fix: "Bring the invoice within the limit, or ask the buyer for a new approval." }),
    APPROVAL_EXPIRED: () => ({ title: "The buyer’s approval had ended",
      body: `It ended on ${date(f.ordered)}; the invoice is dated ${date(f.invoiced)}.`,
      fix: "Ask the buyer to renew the order before you deliver." }),
    ADDRESS_DIFFERS: () => ({ title: "Delivery address", body: `The order ships to ${f.ordered ?? "—"}; the invoice says ${f.invoiced ?? "no address"}.`,
      fix: "Use the order’s address, or get the buyer to confirm the new one." }),
    CURRENCY_DIFFERS: () => ({ title: "Currency", body: `The order is in ${f.ordered}; the invoice is in ${f.invoiced}.`,
      fix: "Invoice in the order’s currency. SAL never converts between currencies." }),
  };
  return table[f.code]();
}

/** A held deal as a short to-do: what differs, how to fix each, and the two steps that clear the hold. */
export function HeldDeal({ deal, paypal = false }: { deal: Deal; paypal?: boolean }) {
  const currency = deal.purchase_order.currency;
  const n = deal.findings.length;
  return (
    <li className="lp-card flex flex-col gap-5 p-5 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-0.5">
          <h3 className="text-[18px] font-semibold">{deal.deal_ref}</h3>
          <span className="muted text-[15px]">
            {deal.purchase_order.approved_by}
            {deal.invoice ? ` · invoice ${deal.invoice.invoice_ref}, ${amount(deal.invoice.total, deal.invoice.currency)}` : ""}
          </span>
        </div>
        <span className="rounded-full bg-red-bg px-3 py-1 text-[14px] font-semibold text-red-ink">Don’t deliver yet</span>
      </div>

      <div className="flex flex-col gap-2">
        <p className="text-[15px] font-semibold">{n === 1 ? "1 thing to fix" : `${n} things to fix`}</p>
        <ul className="flex flex-col gap-2">
          {deal.findings.map((f) => {
            const e = explain(f, currency);
            return (
              <li key={`${f.code}:${f.field}`} className="flex gap-3 rounded-2xl bg-(--lp-card-2) p-4">
                <span aria-hidden="true" className="mt-2 h-2 w-2 shrink-0 rounded-full bg-red-ink" />
                <div className="flex min-w-0 flex-col gap-0.5 text-[15px]">
                  <span className="font-semibold [overflow-wrap:anywhere]">{e.title}</span>
                  <span className="muted [overflow-wrap:anywhere]">{e.body}</span>
                  <span><span className="font-semibold">Fix: </span>{e.fix}</span>
                </div>
              </li>
            );
          })}
        </ul>
      </div>

      <div className="grid gap-4 border-t border-(--lp-line) pt-4 md:grid-cols-2">
        <div className="flex flex-col gap-2">
          <p className="text-[15px] font-semibold">1. Tell the other side</p>
          <RequestCorrection deal={deal} />
        </div>
        <div className="flex flex-col items-start gap-2">
          <p className="text-[15px] font-semibold">2. Add the corrected invoice</p>
          <p className="muted text-[14px]">SAL checks it again at once. The hold ends when it matches.</p>
          <DealDocumentUpload dealRef={deal.deal_ref} />
          {paypal && <PayPalInvoiceCheck dealRef={deal.deal_ref} />}
        </div>
      </div>
    </li>
  );
}
