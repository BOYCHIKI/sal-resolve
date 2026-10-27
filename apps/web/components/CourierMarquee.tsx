/*
 * The couriers SAL reads off a tracking document, as two scrolling rows. The names mirror apps/api/app/carriers.py
 * (KNOWN and NAMED_OTHER); keep them in step when a courier is added there. The tag is where the courier works.
 */
export const COURIERS: [name: string, where: string][] = [
  ["JNE", "ID"], ["Pos Indonesia", "ID"], ["TIKI", "ID"], ["AnterAja", "ID"], ["Lion Parcel", "ID"], ["ID Express", "ID"],
  ["Wahana", "ID"], ["SAP Express", "ID"], ["SiCepat", "ID"], ["Paxel", "ID"], ["GoSend", "ID"],
  ["PHLPost", "PH"], ["2GO", "PH"], ["Air21", "PH"], ["LBC Express", "PH"],
  ["Viettel Post", "VN"], ["Vietnam Post", "VN"], ["Giao Hang Nhanh", "VN"], ["GHTK", "VN"],
  ["Thailand Post", "TH"], ["Kerry Express", "TH"], ["Flash Express", "TH"],
  ["Pos Laju", "MY"], ["Pos Malaysia", "MY"], ["GDEX", "MY"], ["City-Link Express", "MY"],
  ["SingPost", "SG"], ["Speedpost", "SG"], ["Janio", "SG"],
  ["J&T Express", "SEA"], ["Ninja Van", "SEA"], ["Shopee Express", "SEA"], ["Lazada Express", "SEA"], ["GrabExpress", "SEA"], ["Lalamove", "SEA"],
  ["USPS", "INTL"], ["FedEx", "INTL"], ["UPS", "INTL"], ["DHL", "INTL"], ["TNT", "INTL"], ["Aramex", "INTL"], ["Royal Mail", "INTL"],
];

// Markets with local couriers: the country tags only, since SEA and INTL couriers work across markets.
export const MARKETS = new Set(COURIERS.map(([, where]) => where).filter((w) => w.length === 2)).size;

function Row({ items, hidden }: { items: typeof COURIERS; hidden?: boolean }) {
  return (
    <ul aria-hidden={hidden || undefined} className="marquee-row">
      {items.map(([name, where]) => (
        <li key={name} className="courier-chip">
          <span>{name}</span>
          <span className="courier-tag">{where}</span>
        </li>
      ))}
    </ul>
  );
}

export function CourierMarquee() {
  const half = Math.ceil(COURIERS.length / 2);
  const rows = [COURIERS.slice(0, half), COURIERS.slice(half)];
  // Each row is two copies side by side so the loop has no seam; the copy is hidden from screen readers.
  // Focusable so the rows can be scrolled with the keyboard where they become swipeable (globals.css).
  return (
    <div role="region" tabIndex={0} aria-label="Couriers SAL recognises" className="flex flex-col gap-3">
      {rows.map((items, i) => (
        <div key={i} className="marquee">
          <div className={`marquee-track ${i === 1 ? "marquee-reverse" : ""}`}>
            <Row items={items} />
            <Row items={items} hidden />
          </div>
        </div>
      ))}
    </div>
  );
}
