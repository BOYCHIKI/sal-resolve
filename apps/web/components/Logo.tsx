/** SAL's mark: two documents, the order behind and the invoice in front, with a check where they match. The same
 *  drawing is app/icon.svg, the browser tab icon. */
export function LogoMark({ size = 28 }: { size?: number }) {
  return (
    <svg aria-hidden="true" width={size} height={size} viewBox="0 0 32 32" className="shrink-0">
      <defs>
        <linearGradient id="sal-mark" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#5b85ff" />
          <stop offset="1" stopColor="#2f52f0" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="8" fill="url(#sal-mark)" />
      <rect x="7" y="6" width="13" height="17" rx="2.5" fill="#fff" opacity="0.45" />
      <rect x="12" y="9" width="13" height="17" rx="2.5" fill="#fff" />
      <path d="M15.3 17.7l2.4 2.4 4.4-5" fill="none" stroke="#2f52f0" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** The mark with the name, for page headers and footers. */
export function Logo() {
  return (
    <span className="display inline-flex items-center gap-2 text-xl whitespace-nowrap">
      <LogoMark />
      <span>SAL <span className="muted font-semibold">Resolve</span></span>
    </span>
  );
}
