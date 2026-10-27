/**
 * SAL, the shield mascot, as an animatable SVG. Same proportions and colours as the demo video
 * (demo-video/promo.py `mascot`), split into parts that CSS can move: body bob, eye blink, arm wave.
 * Static PNG poses of the exact video renders live in /public/mascot/ (sal-idle, sal-happy, sal-focus, ...).
 *
 * Motion respects prefers-reduced-motion. Decorative by default (aria-hidden); pass `label` to announce it.
 */
type Pose = "idle" | "wave" | "happy";

type Props = {
  pose?: Pose;
  size?: number;        // rendered height in px
  animate?: boolean;
  label?: string;
  className?: string;
};

// Arm angle in degrees from hanging straight down; + raises it outward. Matches promo.py `arms`.
const ARMS: Record<Pose, [number, number]> = { idle: [10, 10], wave: [10, 160], happy: [20, 150] };

const NAVY = "#102040";
const ARM = "#004EAA";

export function SalMascot({ pose = "idle", size = 220, animate = true, label, className }: Props) {
  const [left, right] = ARMS[pose];
  const id = `sal-${pose}`;
  return (
    <svg
      viewBox="-72 -46 276 272"
      height={size}
      width={(size * 276) / 272}
      className={className}
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      data-animate={animate ? "on" : "off"}
    >
      <style>{`
        @keyframes sal-bob { 0%,100% { transform: translateY(0) } 50% { transform: translateY(-6px) } }
        @keyframes sal-shadow { 0%,100% { transform: scaleX(1); opacity:.27 } 50% { transform: scaleX(.86); opacity:.18 } }
        @keyframes sal-blink { 0%,92%,100% { transform: scaleY(1) } 95% { transform: scaleY(.08) } }
        @keyframes sal-wave { 0%,100% { transform: rotate(var(--arm)) } 50% { transform: rotate(calc(var(--arm) - 18deg)) } }
        @keyframes sal-twinkle { 0%,100% { opacity:1; transform: scale(1) } 50% { opacity:.55; transform: scale(.8) } }
        [data-animate="on"] .sal-bob { animation: sal-bob 2.8s ease-in-out infinite }
        [data-animate="on"] .sal-shadow { animation: sal-shadow 2.8s ease-in-out infinite; transform-origin: 66px 192px }
        [data-animate="on"] .sal-eye { animation: sal-blink 4.2s infinite; transform-box: fill-box; transform-origin: center }
        [data-animate="on"] .sal-arm-r.sal-moving { animation: sal-wave 1.1s ease-in-out infinite }
        [data-animate="on"] .sal-spark { animation: sal-twinkle 1.6s ease-in-out infinite; transform-box: fill-box; transform-origin: center }
        @media (prefers-reduced-motion: reduce) { .sal-bob, .sal-shadow, .sal-eye, .sal-arm-r, .sal-spark { animation: none !important } }
      `}</style>
      <defs>
        <linearGradient id={`${id}-body`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#409CFF" />
          <stop offset="1" stopColor="#004EAA" />
        </linearGradient>
        <filter id={`${id}-soft`} x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="4" />
        </filter>
      </defs>

      {/* ground shadow */}
      <ellipse className="sal-shadow" cx="66" cy="192" rx="55" ry="8" fill="rgba(20,40,80,.27)" filter={`url(#${id}-soft)`} />

      <g className="sal-bob">
        {/* arms sit behind the body; each rotates around its shoulder */}
        <g className="sal-arm-l" transform={`rotate(${left} 13.2 84.5)`}>
          <line x1="13.2" y1="84.5" x2="13.2" y2="144.5" stroke={ARM} strokeWidth="23" strokeLinecap="round" />
          <circle cx="13.2" cy="144.5" r="15" fill={ARM} />
        </g>
        <g
          className={`sal-arm-r${pose === "wave" ? " sal-moving" : ""}`}
          style={{ ["--arm" as string]: `${-right}deg`, transformOrigin: "118.8px 84.5px", transform: `rotate(${-right}deg)` }}
        >
          <line x1="118.8" y1="84.5" x2="118.8" y2="144.5" stroke={ARM} strokeWidth="23" strokeLinecap="round" />
          <circle cx="118.8" cy="144.5" r="15" fill={ARM} />
        </g>

        {/* sparkles by the raised hand, placed like promo.py: offsets in hand radii (15) from the hand */}
        {pose === "happy" && (() => {
          const a = (right * Math.PI) / 180;
          const hx = 118.8 + 60 * Math.sin(a), hy = 84.5 + 60 * Math.cos(a);
          return (
            <g fill="#FFC43C">
              {[[1.9, -1.7, 1.0], [0.7, -2.9, 0.6], [2.8, -0.6, 0.5]].map(([ox, oy, k], i) => {
                const x = hx + 15 * ox, y = hy + 15 * oy, r = 15 * k;
                return (
                  <path key={i} className="sal-spark" style={{ animationDelay: `${i * 0.3}s` }}
                    d={`M${x},${y - 1.6 * r} L${x + 0.45 * r},${y - 0.45 * r} L${x + 1.6 * r},${y} L${x + 0.45 * r},${y + 0.45 * r}
                       L${x},${y + 1.6 * r} L${x - 0.45 * r},${y + 0.45 * r} L${x - 1.6 * r},${y} L${x - 0.45 * r},${y - 0.45 * r} Z`} />
                );
              })}
            </g>
          );
        })()}

        {/* shield body */}
        <path
          d="M0,44.9 A44.9,44.9 0 0 1 44.9,0 L87.1,0 A44.9,44.9 0 0 1 132,44.9 L132,70.4 Q129.4,151.4 66,176 Q2.6,151.4 0,70.4 Z"
          fill={`url(#${id}-body)`}
        />
        <ellipse cx="44.9" cy="30.8" rx="34.3" ry="22.9" fill="rgba(255,255,255,.27)" filter={`url(#${id}-soft)`} />

        {/* face plate */}
        <rect x="21.1" y="24.6" width="89.8" height="63.4" rx="26.4" fill="#FAFCFF" />
        {pose === "idle" ? (
          [-1, 1].map((s) => (
            <g key={s} className="sal-eye">
              <ellipse cx={66 + s * 17.2} cy="54.6" rx="8.2" ry="10.8" fill={NAVY} />
              <circle cx={66 + s * 17.2 - 1.2} cy="50.8" r="3.1" fill="#fff" />
            </g>
          ))
        ) : (
          [-1, 1].map((s) => (
            <path key={s} d={`M${66 + s * 17.2 - 7.4},${54.6 + 1.6} A7.9,7.1 0 0 1 ${66 + s * 17.2 + 7.4},${54.6 + 1.6}`}
              fill="none" stroke={NAVY} strokeWidth="5.6" strokeLinecap="round" />
          ))
        )}
        {/* cheeks */}
        <ellipse cx="36.3" cy="66.9" rx="6.6" ry="2.6" fill="rgba(255,140,150,.43)" />
        <ellipse cx="95.7" cy="66.9" rx="6.6" ry="2.6" fill="rgba(255,140,150,.43)" />
        {/* smile */}
        <path d={pose === "idle" ? "M73.4,73 A7.9,7.1 0 0 1 58.6,73" : "M75.3,72.9 A9.9,8.9 0 0 1 56.7,72.9"}
          fill="none" stroke={NAVY} strokeWidth="4.4" strokeLinecap="round" />

        {/* check badge */}
        <circle cx="66" cy="119.7" r="15.8" fill="rgba(255,255,255,.92)" />
        <path d="M58.9,120 L64.4,125.7 L73.9,114.2" fill="none" stroke="#0066CC" strokeWidth="5.2"
          strokeLinecap="round" strokeLinejoin="round" />
      </g>
    </svg>
  );
}
