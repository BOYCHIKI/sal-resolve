// Money is shown exactly as the API sends it: original currency, decimal string, never converted.
export function money(m: { value: string; currency: string }): string {
  return `${m.value} ${m.currency}`;
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
