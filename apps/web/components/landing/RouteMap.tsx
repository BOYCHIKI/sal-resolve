/*
 * The six Southeast Asian markets whose local couriers SAL reads (apps/api/app/carriers.py), placed roughly where
 * they sit on a map and joined by dashed shipping lanes, with parcels travelling a few of them (Motion.tsx, data-orbit).
 * Decorative; the figures beside it carry the meaning.
 */
const NODES = {
  TH: [150, 120], VN: [270, 90], PH: [470, 150], MY: [190, 300], SG: [235, 360], ID: [380, 430],
} as const;
const LANES: [keyof typeof NODES, keyof typeof NODES][] = [["TH", "VN"], ["VN", "PH"], ["TH", "MY"], ["MY", "SG"], ["SG", "ID"], ["PH", "ID"], ["VN", "SG"]];
// Lanes with a parcel on them, and how long one trip takes.
const PARCELS = [["THVN", 7], ["VNPH", 9], ["MYSG", 5], ["PHID", 8], ["VNSG", 11]] as const;

export function RouteMap() {
  return (
    <svg aria-hidden="true" data-orbit viewBox="0 0 600 520" className="h-auto w-full" fill="none">
      {LANES.map(([a, b]) => {
        const [x1, y1] = NODES[a];
        const [x2, y2] = NODES[b];
        const mx = (x1 + x2) / 2 + (y2 - y1) * 0.18;
        const my = (y1 + y2) / 2 - (x2 - x1) * 0.18;
        return <path key={a + b} id={`lane-${a}${b}`} d={`M${x1} ${y1} Q${mx} ${my} ${x2} ${y2}`} stroke="var(--lp-line-strong)" strokeDasharray="3 6" />;
      })}
      <path d={`M${NODES.SG[0]} ${NODES.SG[1]} Q${330} ${300} ${NODES.ID[0]} ${NODES.ID[1]}`} stroke="var(--lp-mint)" strokeWidth="1.5" strokeDasharray="3 6" className="lane-live" />
      {PARCELS.map(([lane, seconds], i) => (
        <g key={lane} className="orbit-dot" data-path={`#lane-${lane}`} data-start={i * 0.13} data-seconds={seconds}>
          <rect x="-4" y="-4" width="8" height="8" transform="rotate(45)" fill="var(--lp-mint)" />
        </g>
      ))}
      {Object.entries(NODES).map(([code, [x, y]]) => (
        <g key={code}>
          <circle cx={x} cy={y} r="22" stroke="var(--lp-line-strong)" />
          <circle cx={x} cy={y} r="4" fill={code === "SG" || code === "ID" ? "var(--lp-mint)" : "var(--lp-ink)"} />
          <text x={x} y={y + 44} textAnchor="middle" fill="var(--lp-muted)" fontSize="13" fontWeight="600" letterSpacing="0.08em">{code}</text>
        </g>
      ))}
    </svg>
  );
}
