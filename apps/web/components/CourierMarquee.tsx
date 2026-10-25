/*
 * The couriers SAL reads off a tracking document, as a scrolling strip. The names mirror apps/api/app/carriers.py
 * (KNOWN and NAMED_OTHER); keep them in step when a courier is added there.
 */
export const COURIERS = [
  "JNE", "Pos Indonesia", "TIKI", "AnterAja", "Lion Parcel", "ID Express", "Wahana", "SAP Express", "SiCepat", "Paxel",
  "GoSend", "J&T Express", "PHLPost", "2GO", "Air21", "LBC Express", "Viettel Post", "Vietnam Post", "Giao Hang Nhanh",
  "GHTK", "Thailand Post", "Kerry Express", "Flash Express", "Pos Laju", "Pos Malaysia", "GDEX", "City-Link Express",
  "SingPost", "Speedpost", "Janio", "Ninja Van", "Shopee Express", "Lazada Express", "GrabExpress", "Lalamove",
  "USPS", "FedEx", "UPS", "DHL", "TNT", "Aramex", "Royal Mail",
];

export function CourierMarquee() {
  const row = (hidden: boolean) => (
    <ul aria-hidden={hidden || undefined} className="marquee-row">
      {COURIERS.map((c) => (
        <li key={c} className="rounded-full border border-hairline px-4 py-2 text-[15px] whitespace-nowrap text-ink-soft">{c}</li>
      ))}
    </ul>
  );
  // Two copies side by side so the loop has no seam; the second is hidden from screen readers.
  return (
    // Focusable so the strip can be scrolled with the keyboard where it becomes a swipeable row (globals.css).
    <div className="marquee" role="region" tabIndex={0} aria-label="Couriers SAL recognises">
      <div className="marquee-track">
        {row(false)}
        {row(true)}
      </div>
    </div>
  );
}
