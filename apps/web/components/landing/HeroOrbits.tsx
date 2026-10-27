/*
 * Behind the landing hero: dashed rings rising from below the fold like a scan, with small diamonds travelling
 * along them (Motion.tsx, data-orbit). Decorative. Without motion the rings stay and the diamonds are hidden
 * (globals.css, .orbit-dot), since they would otherwise sit at the corner of the drawing.
 */
const CX = 720;
const CY = 1060;
const RINGS = [340, 470, 610, 760, 920];

// Two diamonds per ring, alternating direction; start is a fraction of the ring (0 = the ring's left edge).
const DOTS = RINGS.flatMap((r, i) => [
  { ring: i, start: 0.08 + i * 0.07, tone: i % 2 ? "var(--lp-blue)" : "var(--lp-mint)", seconds: 34 + i * 9, reverse: i % 2 === 1 },
  { ring: i, start: 0.42 + i * 0.05, tone: "var(--lp-blue)", seconds: 46 + i * 11, reverse: i % 2 === 0 },
]);

// A circle as a path that starts on its left edge, so MotionPath has something to follow.
const ring = (r: number) => `M${CX - r} ${CY} a${r} ${r} 0 1 1 ${2 * r} 0 a${r} ${r} 0 1 1 ${-2 * r} 0`;

export function HeroOrbits() {
  return (
    <svg aria-hidden="true" data-orbit data-orbit-origin={`${CX} ${CY}`} viewBox="0 0 1440 900" preserveAspectRatio="xMidYMax slice"
      className="lp-fade pointer-events-none absolute inset-x-0 top-0 h-[900px] w-full" fill="none">
      {RINGS.map((r, i) => (
        <path key={r} id={`orbit-${i}`} d={ring(r)} stroke="var(--lp-line-strong)" strokeDasharray="2 7" />
      ))}
      {DOTS.map((d, i) => (
        <g key={i} className="orbit-dot" data-path={`#orbit-${d.ring}`} data-start={d.start} data-seconds={d.seconds}
          data-reverse={d.reverse || undefined}>
          <rect x="-5" y="-5" width="10" height="10" transform="rotate(45)" fill={d.tone} />
        </g>
      ))}
    </svg>
  );
}
