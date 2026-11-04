/* The strip above the landing nav: short true facts about SAL, on the marquee loop (globals.css, .ticker). */
const ITEMS = [
  "Nothing sent without your approval",
  "Facts from your documents and PayPal",
  "Orders checked before delivery",
  "Built on PayPal’s Disputes API",
];

export function Ticker() {
  return (
    <div className="ticker marquee">
      <div className="marquee-track">
        {[false, true].map((hidden) => (
          <ul key={String(hidden)} aria-hidden={hidden || undefined} className="marquee-row">
            {ITEMS.map((t) => (
              <li key={t} className="flex items-center gap-3 whitespace-nowrap">
                <span aria-hidden="true" className="text-(--lp-mint)">+</span>{t}
              </li>
            ))}
          </ul>
        ))}
      </div>
    </div>
  );
}
