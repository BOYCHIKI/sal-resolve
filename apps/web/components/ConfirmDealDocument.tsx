"use client";

import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";
import { confirmDealDocument, discardDealDocument } from "@/app/actions";
import type { DealDocument, ProposedItem, ProvenValue } from "@/lib/api";

const DEFAULT_APPROVAL_DAYS = 90;
const INPUT = "min-h-11 w-full rounded-xl border bg-white px-3 py-2 text-[15px] font-normal";
type Row = { item_code: string; description: string; quantity: string; unit_price: string };
const EMPTY_ROW: Row = { item_code: "", description: "", quantity: "", unit_price: "" };

const REFUSED: Record<string, string> = {
  DEAL_EXISTS: "A deal with this PO number already exists.",
  DEAL_NOT_FOUND: "That deal no longer exists.",
  DOCUMENT_NOT_OPEN: "This document was already handled.",
  HTTP_422: "Check the format: amounts like 1200.00, a 3-letter currency (USD), a 2-letter country (AU), dates as YYYY-MM-DD.",
};

function toRow(item: ProposedItem): Row {
  return { item_code: item.item_code.value ?? "", description: item.description.value ?? "",
    quantity: item.quantity.value ?? "", unit_price: item.unit_price.value ?? "" };
}

function daysFromNow(days: number): string {
  return new Date(Date.now() + days * 86_400_000).toISOString().slice(0, 10);
}

/** One value: what SAL read, where it read it, and a box to correct it. A blank box is one SAL couldn't find. */
function Field({ label, value, onChange, proven, optional, hint, wide }: {
  label: string; value: string; onChange: (v: string) => void; proven?: ProvenValue; optional?: boolean; hint?: string; wide?: boolean;
}) {
  const id = useId();
  const blank = !value.trim() && !optional;
  return (
    <div className={`flex min-w-0 flex-col gap-1 ${wide ? "sm:col-span-2" : ""}`}>
      <label htmlFor={id} className="flex flex-wrap items-baseline justify-between gap-x-2 text-[14px] font-semibold">
        <span>{label}{optional && <span className="muted font-normal"> (optional)</span>}</span>
        <span className={`text-[12px] font-normal ${blank ? "text-red-ink" : "muted"}`}>
          {blank ? "Not found, please type it" : proven?.line ? `From line ${proven.line}` : ""}
        </span>
      </label>
      <input id={id} value={value} onChange={(e) => onChange(e.target.value)} aria-invalid={blank}
        className={`${INPUT} ${blank ? "border-red-ink" : "border-(--lp-line-strong)"}`} />
      {hint && <span className="text-[12px] text-amber-ink">{hint}</span>}
    </div>
  );
}

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <fieldset className="flex min-w-0 flex-col gap-3">
      <legend className="mb-1 text-[13px] font-semibold uppercase tracking-wide text-(--lp-muted)">{title}</legend>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">{children}</div>
    </fieldset>
  );
}

/** A read document waiting for the seller: a row on the page, and a dialog with the page beside every value SAL read.
 *  A proven value can still be a misread, so every value stays editable; a blank means SAL couldn't prove it. */
export function ConfirmDealDocument({ doc, openOnLoad = false }: { doc: DealDocument; openOnLoad?: boolean }) {
  const router = useRouter();
  const dialog = useRef<HTMLDialogElement>(null);
  // Opened straight from the upload dialog once SAL has read the document (/deals?open=<id>).
  useEffect(() => {
    if (openOnLoad && !dialog.current?.open) dialog.current?.showModal();
  }, [openOnLoad]);
  const titleId = useId();
  const p = doc.proposal;
  const isInvoice = doc.kind === "INVOICE";
  const lines = doc.lines ?? [];
  const [reference, setReference] = useState(p?.reference.value ?? "");
  const [party, setParty] = useState(p?.party.value ?? "");
  const [date, setDate] = useState(isInvoice ? (p?.issued_on.value ?? "") : daysFromNow(DEFAULT_APPROVAL_DAYS));
  const [category, setCategory] = useState("GOODS");
  const [currency, setCurrency] = useState(p?.currency.value ?? "");
  const [total, setTotal] = useState(p?.total.value ?? "");
  const [shipping, setShipping] = useState(p?.shipping.value ?? "");
  const [tax, setTax] = useState(p?.tax.value ?? "");
  const [country, setCountry] = useState(p?.ship_country.value ?? "");
  const [city, setCity] = useState(p?.ship_city.value ?? "");
  const [postal, setPostal] = useState(p?.ship_postal_code.value ?? "");
  const [transaction, setTransaction] = useState("");
  const [rows, setRows] = useState<Row[]>(p?.items.length ? p.items.map(toRow) : [EMPTY_ROW]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const setRow = (i: number, key: keyof Row, value: string) =>
    setRows(rows.map((r, n) => (n === i ? { ...r, [key]: value } : r)));

  async function decide(run: () => Promise<{ ok: true } | { ok: false; code: string; message: string }>) {
    setBusy(true);
    setError("");
    const result = await run();
    setBusy(false);
    if (result.ok) {
      dialog.current?.close();
      router.refresh();
    } else setError(REFUSED[result.code] ?? result.message);
  }

  function confirm() {
    const shipTo = country.trim() ? { country: country.trim(), city: city.trim(), postal_code: postal.trim() || null } : null;
    const body = isInvoice
      ? { invoice_ref: reference.trim(), issued_at: `${date.trim()}T00:00:00Z`, currency: currency.trim(), total: total.trim(),
          shipping: shipping.trim() || "0", tax: tax.trim() || "0", ship_to: shipTo, lines: rows,
          paypal_transaction_id: transaction.trim() || null }
      : { deal_ref: reference.trim(), category, currency: currency.trim(), max_total: total.trim(), approved_by: party.trim(),
          expires_at: `${date.trim()}T23:59:59Z`, ship_to: shipTo, lines: rows };
    return decide(() => confirmDealDocument(doc.id, doc.kind, body));
  }

  const needsAddress = isInvoice || category === "GOODS";
  const required = [reference, date, currency, total, ...(isInvoice ? [] : [party]), ...(needsAddress ? [country, city] : []),
    ...rows.flatMap((r) => Object.values(r))];
  const blanks = required.filter((v) => !v.trim()).length;
  // An invoice that never names its order may have been added to the wrong one.
  const orderRef = doc.deal_ref;
  const wrongOrder = isInvoice && !!orderRef && lines.length > 0 && !lines.some((line) => line.text.includes(orderRef));
  const name = isInvoice ? "Invoice" : "Purchase order";

  return (
    <li className="lp-card flex flex-wrap items-center justify-between gap-x-6 gap-y-3 px-5 py-4 sm:px-6">
      <div className="flex min-w-0 flex-col gap-0.5">
        <span className="text-[16px] font-semibold">
          {name} {reference || ""}{isInvoice && doc.deal_ref ? <span className="muted font-normal"> · for {doc.deal_ref}</span> : null}
        </span>
        <span className="muted text-[14px]">
          SAL has read it. {blanks ? `${blanks} value${blanks === 1 ? "" : "s"} to fill in, then confirm.` : "Check the values, then confirm."}
        </span>
      </div>
      <button type="button" onClick={() => dialog.current?.showModal()} className="lp-btn whitespace-nowrap text-[15px]">Review and confirm</button>

      <dialog ref={dialog} aria-labelledby={titleId}
        onClose={() => { if (openOnLoad) router.replace("/deals?view=confirm", { scroll: false }); }}
        className="m-auto max-h-[calc(100dvh-32px)] w-[min(1080px,calc(100vw-32px))] overflow-hidden rounded-3xl border border-(--lp-line) bg-white p-0 text-(--lp-ink) shadow-2xl backdrop:bg-slate-900/40 backdrop:backdrop-blur-sm">
        <div className="flex max-h-[calc(100dvh-32px)] flex-col">
          <header className="flex items-start justify-between gap-4 border-b border-(--lp-line) px-6 py-5 sm:px-8">
            <div className="flex flex-col gap-1">
              <h2 id={titleId} className="text-[22px] font-semibold tracking-tight">Check the {name.toLowerCase()}</h2>
              <p className="muted text-[15px]">
                SAL read these values from the page shown here. Compare each one, fix anything wrong, then confirm.
                Nothing is saved until you do.
              </p>
            </div>
            <button type="button" onClick={() => dialog.current?.close()} aria-label="Close"
              className="muted -mr-2 grid h-10 w-10 shrink-0 place-items-center rounded-full text-[22px] hover:bg-(--lp-card-2)">×</button>
          </header>

          <div className="flex min-h-0 flex-1 flex-col overflow-y-auto lg:grid lg:grid-cols-[minmax(0,1fr)_minmax(0,1.35fr)] lg:overflow-hidden">
            <section aria-label="The page as SAL read it" className="flex max-h-60 shrink-0 flex-col gap-2 overflow-y-auto border-b border-(--lp-line) bg-(--lp-card-2) px-6 py-5 sm:px-8 lg:max-h-none lg:min-h-0 lg:border-b-0 lg:border-r">
              <h3 className="text-[14px] font-semibold">The page as SAL read it</h3>
              <ol className="flex flex-col font-mono text-[13px]">
                {lines.map((line) => (
                  <li key={line.line} className="flex gap-3 py-0.5">
                    <span className="muted w-6 shrink-0 text-right tabular-nums">{line.line}</span>
                    <span className="[overflow-wrap:anywhere]">{line.text}</span>
                  </li>
                ))}
              </ol>
            </section>

            <div className="flex min-w-0 shrink-0 flex-col gap-6 px-6 py-5 sm:px-8 lg:min-h-0 lg:shrink lg:overflow-y-auto">
              {wrongOrder && (
                <p role="alert" className="rounded-xl bg-amber-bg px-4 py-3 text-[14px] text-amber-ink">
                  This invoice doesn’t mention {doc.deal_ref}. Check it belongs to that order before you confirm, or discard it.
                </p>
              )}

              <Group title={isInvoice ? "Invoice" : "Order"}>
                <Field label={isInvoice ? "Invoice number" : "PO number"} value={reference} onChange={setReference}
                  proven={p?.reference} hint="Check each character: letters and numbers are easy to misread." />
                {isInvoice ? (
                  <Field label="Issued on (YYYY-MM-DD)" value={date} onChange={setDate} proven={p?.issued_on} />
                ) : (
                  <>
                    <Field label="Approved by" value={party} onChange={setParty} proven={p?.party}
                      hint="The person who approved the order, not the company." />
                    <Field label="Approval ends (YYYY-MM-DD)" value={date} onChange={setDate}
                      hint={`Set to ${DEFAULT_APPROVAL_DAYS} days from today. Change it if the PO says otherwise.`} />
                    <div className="flex flex-col gap-1">
                      <label htmlFor={`${titleId}-cat`} className="text-[14px] font-semibold">What was ordered?</label>
                      <select id={`${titleId}-cat`} value={category} onChange={(e) => setCategory(e.target.value)}
                        className={`${INPUT} border-(--lp-line-strong)`}>
                        <option value="GOODS">Goods (shipped)</option>
                        <option value="DIGITAL">Digital</option>
                        <option value="SERVICE">Service</option>
                      </select>
                    </div>
                  </>
                )}
              </Group>

              <Group title="Money">
                <Field label="Currency" value={currency} onChange={setCurrency} proven={p?.currency} />
                <Field label={isInvoice ? "Total" : "Approved limit"} value={total} onChange={setTotal} proven={p?.total} />
                {isInvoice && (
                  <>
                    <Field label="Shipping" value={shipping} onChange={setShipping} proven={p?.shipping} optional />
                    <Field label="Tax" value={tax} onChange={setTax} proven={p?.tax} optional />
                    <Field label="PayPal transaction ID" value={transaction} onChange={setTransaction} optional wide
                      hint="Add it if the buyer has paid, so this invoice joins any dispute on that payment." />
                  </>
                )}
              </Group>

              {needsAddress && (
                <Group title="Delivery">
                  <Field label="Country (2 letters)" value={country} onChange={setCountry} proven={p?.ship_country} />
                  <Field label="City" value={city} onChange={setCity} proven={p?.ship_city} />
                  <Field label="Postal code" value={postal} onChange={setPostal} proven={p?.ship_postal_code} optional />
                </Group>
              )}

              <fieldset className="flex min-w-0 flex-col gap-2">
                <legend className="mb-1 text-[13px] font-semibold uppercase tracking-wide text-(--lp-muted)">Items</legend>
                <div className="overflow-x-auto rounded-xl border border-(--lp-line)">
                  <table className="w-full min-w-[440px] text-[14px]">
                    <thead className="bg-(--lp-card-2) text-left text-[13px]">
                      <tr>
                        <th scope="col" className="px-3 py-2 font-semibold">Item code</th>
                        <th scope="col" className="px-3 py-2 font-semibold">Description</th>
                        <th scope="col" className="w-16 px-3 py-2 font-semibold">Qty</th>
                        <th scope="col" className="w-24 px-3 py-2 font-semibold">Unit price</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((row, i) => (
                        <tr key={i} className="border-t border-(--lp-line)">
                          {(Object.keys(EMPTY_ROW) as (keyof Row)[]).map((key) => (
                            <td key={key} className="px-2 py-1.5">
                              <input value={row[key]} onChange={(e) => setRow(i, key, e.target.value)}
                                aria-label={`Item ${i + 1} ${key.replace("_", " ")}`} aria-invalid={!row[key].trim()}
                                className={`w-full rounded-lg border px-2 py-1.5 ${row[key].trim() ? "border-transparent hover:border-(--lp-line-strong)" : "border-red-ink"}`} />
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <button type="button" onClick={() => setRows([...rows, EMPTY_ROW])}
                  className="self-start py-1 text-[14px] font-semibold text-(--lp-blue) hover:underline">+ Add an item</button>
              </fieldset>
            </div>
          </div>

          <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-(--lp-line) px-6 py-4 sm:px-8">
            <button type="button" onClick={() => decide(() => discardDealDocument(doc.id))} disabled={busy}
              className="px-1 py-2 text-[15px] text-red-ink hover:underline">Discard this document</button>
            <div className="flex flex-wrap items-center gap-3">
              {error && <p role="alert" className="text-[14px] text-red-ink">{error}</p>}
              {!error && blanks > 0 && <span className="muted text-[14px]">{blanks} empty value{blanks === 1 ? "" : "s"} left</span>}
              <button type="button" onClick={() => dialog.current?.close()} className="muted px-3 py-2 text-[15px] hover:underline">Later</button>
              <button type="button" onClick={confirm} disabled={busy} className="lp-btn text-[15px]">
                {busy ? "Saving…" : "Confirm"}
              </button>
            </div>
          </footer>
        </div>
      </dialog>
    </li>
  );
}
