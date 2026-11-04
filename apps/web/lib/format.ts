/** The currency's usual decimals (USD 2, JPY 0, KWD 3); none for a malformed code. */
function minorDigits(currency: string): number {
  try {
    return new Intl.NumberFormat("en", { style: "currency", currency }).resolvedOptions().maximumFractionDigits ?? 0;
  } catch {
    return 0;
  }
}

// A symbol for quick reading. Many currencies share "$" or "¥", so the code always follows and decides.
// A fixed table, not Intl, so the server and the browser always print the same thing.
const SYMBOLS: Record<string, string> = {
  USD: "$", AUD: "$", CAD: "$", SGD: "$", HKD: "$", NZD: "$", MXN: "$", EUR: "€", GBP: "£", JPY: "¥", CNY: "¥",
  IDR: "Rp", PHP: "₱", INR: "₹", KRW: "₩", THB: "฿", VND: "₫", MYR: "RM", BRL: "R$",
};

/** "1200" + "USD" → "$1,200.00 USD"; "4500" + "JPY" → "¥4,500 JPY"; "12" + "CHF" → "12.00 CHF". Thousands are grouped
 *  and missing decimals padded with zeros, so the value never changes; digits are never cut or rounded, and the
 *  currency is never converted. A value that isn't a plain decimal is shown as written. */
export function amount(value: string | null | undefined, currency: string | null | undefined): string {
  const code = (currency ?? "").trim().toUpperCase();
  const text = (value ?? "").trim();
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(text);
  if (!match) return [text || "—", code].filter(Boolean).join(" ");
  const [, sign, whole, fraction = ""] = match;
  const decimals = fraction.padEnd(code ? minorDigits(code) : 0, "0");
  const number = `${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}${decimals ? "." + decimals : ""}`;
  return code ? `${sign}${SYMBOLS[code] ?? ""}${number} ${code}` : `${sign}${number}`;
}

export function money(m: { value: string; currency: string }): string {
  return amount(m.value, m.currency);
}

/** Adds decimal strings without floating point, keeping the longest number of decimals: "43.17" + "10.5" → "53.67". */
export function addDecimals(values: string[]): string {
  const valid = values.filter((v) => /^-?\d+(\.\d+)?$/.test(v));
  const scale = Math.max(0, ...valid.map((v) => (v.split(".")[1] ?? "").length));
  const total = valid.reduce((sum, v) => {
    const [whole, fraction = ""] = v.replace("-", "").split(".");
    const units = BigInt(whole + fraction.padEnd(scale, "0"));
    return sum + (v.startsWith("-") ? -units : units);
  }, BigInt(0));
  const negative = total < BigInt(0);
  const digits = (negative ? -total : total).toString().padStart(scale + 1, "0");
  const whole = digits.slice(0, digits.length - scale);
  return `${negative ? "-" : ""}${whole}${scale ? "." + digits.slice(digits.length - scale) : ""}`;
}

export function label(code: string | null | undefined): string {
  if (!code) return "-";
  return code.toLowerCase().replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export function deadline(iso: string | null): { text: string; urgent: boolean } {
  if (!iso) return { text: "No deadline", urgent: false };
  const due = new Date(iso);
  const days = Math.ceil((due.getTime() - Date.now()) / 86_400_000);
  const date = due.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
  if (days < 0) return { text: `${date} (overdue)`, urgent: true };
  return { text: `${date} (${days} day${days === 1 ? "" : "s"})`, urgent: days <= 3 };
}
