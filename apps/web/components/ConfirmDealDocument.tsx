"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { confirmDealDocument, discardDealDocument } from "@/app/actions";
import type { DealDocument, ProposedItem, ProvenValue } from "@/lib/api";

const DEFAULT_APPROVAL_DAYS = 90;
type Row = { item_code: string; description: string; quantity: string; unit_price: string };
const EMPTY_ROW: Row = { item_code: "", description: "", quantity: "", unit_price: "" };

const REFUSED: Record<string, string> = {
  DEAL_EXISTS: "A deal with this PO number already exists.",
  DEAL_NOT_FOUND: "That deal no longer exists.",
  DOCUMENT_NOT_OPEN: "This document was already handled.",
  HTTP_422: "Check the highlighted format: amounts like 1200.00, a 3-letter currency, a 2-letter country.",
};

function toRow(item: ProposedItem): Row {
  return { item_code: item.item_code.value ?? "", description: item.description.value ?? "",
    quantity: item.quantity.value ?? "", unit_price: item.unit_price.value ?? "" };
}

function daysFromNow(days: number): string {
  return new Date(Date.now() + days * 86_400_000).toISOString().slice(0, 10);
}

function Field({ label, value, onChange, proven }: {
  label: string; value: string; onChange: (v: string) => void; proven?: ProvenValue;
}) {
  const blank = !value.trim();
  return (
    <label className="flex flex-col gap-1 text-[14px] font-semibold">
      <span>{label}{proven?.line ? <span className="muted font-normal"> · line {proven.line}</span> : null}</span>
      <input value={value} onChange={(e) => onChange(e.target.value)}
        className={`rounded-lg border bg-white px-3 py-2 font-normal ${blank ? "border-red-ink" : ""}`} />
    </label>
  );
}

/** The page on one side, the values on the other. A blank means SAL could not prove the value, so the seller types it. */
export function ConfirmDealDocument({ doc }: { doc: DealDocument }) {
  const router = useRouter();
  const p = doc.proposal;
  const isInvoice = doc.kind === "INVOICE";
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
    if (result.ok) router.refresh();
    else setError(REFUSED[result.code] ?? result.message);
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

  return (
    <li className="lp-card flex flex-wrap gap-6 px-6 py-5">
      <div className="flex min-w-0 flex-[1_1_300px] flex-col gap-1">
        <h3 className="text-[17px] font-semibold">{isInvoice ? `Invoice for ${doc.deal_ref}` : "Purchase order"}: what SAL read</h3>
        <ol className="muted font-mono text-[13px]">
          {(doc.lines ?? []).map((l) => <li key={l.line}>{l.line}. {l.text}</li>)}
        </ol>
      </div>
      <div className="flex flex-[2_1_420px] flex-col gap-3">
        <p className="muted text-[15px]">Red boxes are values SAL could not find on the page. Check everything, then confirm.</p>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <Field label={isInvoice ? "Invoice number" : "PO number"} value={reference} onChange={setReference} proven={p?.reference} />
          {!isInvoice && <Field label="Approved by" value={party} onChange={setParty} proven={p?.party} />}
          <Field label={isInvoice ? "Issued on (YYYY-MM-DD)" : "Approval ends (YYYY-MM-DD)"} value={date} onChange={setDate}
            proven={isInvoice ? p?.issued_on : undefined} />
          {!isInvoice && (
            <label className="flex flex-col gap-1 text-[14px] font-semibold">
              Category
              <select value={category} onChange={(e) => setCategory(e.target.value)} className="rounded-lg border bg-white px-3 py-2 font-normal">
                <option value="GOODS">Goods</option>
                <option value="DIGITAL">Digital</option>
                <option value="SERVICE">Service</option>
              </select>
            </label>
          )}
          <Field label="Currency" value={currency} onChange={setCurrency} proven={p?.currency} />
          <Field label={isInvoice ? "Total" : "Approved limit"} value={total} onChange={setTotal} proven={p?.total} />
          {isInvoice && <Field label="Shipping" value={shipping} onChange={setShipping} proven={p?.shipping} />}
          {isInvoice && <Field label="Tax" value={tax} onChange={setTax} proven={p?.tax} />}
          {isInvoice && <Field label="PayPal transaction ID" value={transaction} onChange={setTransaction} />}
          <Field label="Country" value={country} onChange={setCountry} proven={p?.ship_country} />
          <Field label="City" value={city} onChange={setCity} proven={p?.ship_city} />
          <Field label="Postal code" value={postal} onChange={setPostal} proven={p?.ship_postal_code} />
        </div>
        {rows.map((row, i) => (
          <div key={i} className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Field label="Item code" value={row.item_code} onChange={(v) => setRow(i, "item_code", v)} proven={p?.items[i]?.item_code} />
            <Field label="Description" value={row.description} onChange={(v) => setRow(i, "description", v)} proven={p?.items[i]?.description} />
            <Field label="Quantity" value={row.quantity} onChange={(v) => setRow(i, "quantity", v)} proven={p?.items[i]?.quantity} />
            <Field label="Unit price" value={row.unit_price} onChange={(v) => setRow(i, "unit_price", v)} proven={p?.items[i]?.unit_price} />
          </div>
        ))}
        <div className="flex flex-wrap items-center gap-4">
          <button type="button" onClick={confirm} disabled={busy} className="lp-btn text-[15px]">
            {busy ? "Saving…" : "Confirm"}
          </button>
          <button type="button" onClick={() => setRows([...rows, EMPTY_ROW])} className="text-[15px] font-semibold underline underline-offset-4">
            Add item
          </button>
          <button type="button" onClick={() => decide(() => discardDealDocument(doc.id))} disabled={busy}
            className="text-[15px] font-semibold underline underline-offset-4">
            Discard
          </button>
        </div>
        {error && <p role="alert" className="text-[15px] text-red-ink">{error}</p>}
      </div>
    </li>
  );
}
