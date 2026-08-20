/**
 * Diagrams for the capability deck.
 *
 * These replace stock photography. A circuit board or a wall of green glyphs
 * says "technology" and nothing else -- it carries no information about what
 * the card claims, and a reader who knows the subject reads it as filler.
 * Each drawing below is the actual shape of the query it sits on: a path that
 * lands, a closure that fans out, a window on a timeline, a search that ends
 * nowhere, a symbol bound across a package boundary.
 *
 * One visual language throughout: 5px nodes, 1.5px edges, the accent reserved
 * for the answer and muted grey for everything the query merely walked past.
 */

const ACCENT = "oklch(0.78 0.155 55)";
const DANGER = "oklch(0.62 0.21 25)";
const MUTED = "oklch(0.45 0.01 70)";
const FAINT = "oklch(0.30 0.008 60)";

interface VisualProps {
  className?: string;
}

const svgProps = {
  viewBox: "0 0 240 160",
  fill: "none" as const,
  xmlns: "http://www.w3.org/2000/svg",
  "aria-hidden": true,
};

/** A call path that lands: entrypoint, two hops, then the vulnerable symbol. */
export function ReachabilityVisual({ className }: VisualProps) {
  const nodes = [
    [30, 30],
    [95, 62],
    [150, 100],
    [210, 130],
  ];
  return (
    <svg {...svgProps} className={className}>
      {/* Edges the search walked past but did not use. */}
      <path d="M30 30 L88 108" stroke={FAINT} strokeWidth="1.5" />
      <path d="M95 62 L60 128" stroke={FAINT} strokeWidth="1.5" />
      <circle cx="88" cy="112" r="4" fill={FAINT} />
      <circle cx="57" cy="132" r="4" fill={FAINT} />

      {/* The path that lands. */}
      <path
        d={`M${nodes[0][0]} ${nodes[0][1]} L${nodes[1][0]} ${nodes[1][1]} L${nodes[2][0]} ${nodes[2][1]} L${nodes[3][0]} ${nodes[3][1]}`}
        stroke={ACCENT}
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {nodes.slice(0, 3).map(([x, y], i) => (
        <circle key={i} cx={x} cy={y} r="5" fill={ACCENT} />
      ))}
      {/* The vulnerable symbol at the end. */}
      <circle cx={nodes[3][0]} cy={nodes[3][1]} r="8" fill={DANGER} />
      <circle cx={nodes[3][0]} cy={nodes[3][1]} r="13" stroke={DANGER} strokeWidth="1.5" opacity="0.5" />
      {/* Entrypoint ring. */}
      <circle cx={nodes[0][0]} cy={nodes[0][1]} r="10" stroke={ACCENT} strokeWidth="1.5" opacity="0.55" />
    </svg>
  );
}

/** Reverse closure: everything that transitively depends on the compromised release. */
export function BlastRadiusVisual({ className }: VisualProps) {
  const ring1 = [
    [120, 42],
    [178, 80],
    [120, 118],
    [62, 80],
  ];
  const ring2 = [
    [120, 12],
    [205, 45],
    [212, 118],
    [120, 148],
    [30, 118],
    [35, 45],
  ];
  return (
    <svg {...svgProps} className={className}>
      <circle cx="120" cy="80" r="38" stroke={FAINT} strokeWidth="1.5" />
      <circle cx="120" cy="80" r="70" stroke={FAINT} strokeWidth="1.5" />

      {ring1.map(([x, y], i) => (
        <line key={`a${i}`} x1="120" y1="80" x2={x} y2={y} stroke={ACCENT} strokeWidth="1.5" opacity="0.75" />
      ))}
      {ring2.map(([x, y], i) => (
        <line
          key={`b${i}`}
          x1={ring1[i % ring1.length][0]}
          y1={ring1[i % ring1.length][1]}
          x2={x}
          y2={y}
          stroke={ACCENT}
          strokeWidth="1.5"
          opacity="0.35"
        />
      ))}

      {ring2.map(([x, y], i) => (
        <circle key={`n2${i}`} cx={x} cy={y} r="4" fill={ACCENT} opacity="0.5" />
      ))}
      {ring1.map(([x, y], i) => (
        <circle key={`n1${i}`} cx={x} cy={y} r="5" fill={ACCENT} opacity="0.85" />
      ))}

      {/* The compromised release at the centre. */}
      <circle cx="120" cy="80" r="9" fill={DANGER} />
    </svg>
  );
}

/** valid_from / valid_to as a window on a timeline, with the query inside it. */
export function TemporalVisual({ className }: VisualProps) {
  return (
    <svg {...svgProps} className={className}>
      <line x1="20" y1="100" x2="220" y2="100" stroke={MUTED} strokeWidth="1.5" />
      {[20, 60, 100, 140, 180, 220].map((x) => (
        <line key={x} x1={x} y1="94" x2={x} y2="106" stroke={FAINT} strokeWidth="1.5" />
      ))}

      {/* The window the release was live in. */}
      <rect x="80" y="52" width="90" height="48" rx="4" fill={ACCENT} opacity="0.16" />
      <line x1="80" y1="46" x2="80" y2="106" stroke={ACCENT} strokeWidth="2" />
      <line x1="170" y1="46" x2="170" y2="106" stroke={ACCENT} strokeWidth="2" />
      <text x="80" y="38" fill={ACCENT} fontSize="11" fontFamily="ui-monospace, monospace">
        from
      </text>
      <text x="170" y="38" fill={ACCENT} fontSize="11" fontFamily="ui-monospace, monospace" textAnchor="end">
        to
      </text>

      {/* A resolution that falls inside it, and one that does not. */}
      <circle cx="125" cy="100" r="7" fill={DANGER} />
      <circle cx="125" cy="100" r="12" stroke={DANGER} strokeWidth="1.5" opacity="0.45" />
      <circle cx="42" cy="100" r="5" fill={FAINT} />
      <circle cx="202" cy="100" r="5" fill={FAINT} />
    </svg>
  );
}

/** A search that completed and found nothing: the frontier, and no edge out of it. */
export function AbstentionVisual({ className }: VisualProps) {
  return (
    <svg {...svgProps} className={className}>
      {/* Explored frontier. */}
      <path d="M28 80 L82 44 M28 80 L82 116 M82 44 L134 30 M82 116 L134 128" stroke={MUTED} strokeWidth="1.5" />
      {[
        [28, 80],
        [82, 44],
        [82, 116],
        [134, 30],
        [134, 128],
      ].map(([x, y], i) => (
        <circle key={i} cx={x} cy={y} r="5" fill={MUTED} />
      ))}

      {/* Where the search stopped -- nothing continues. */}
      <path d="M134 30 L176 44" stroke={MUTED} strokeWidth="1.5" strokeDasharray="3 5" opacity="0.6" />
      <path d="M134 128 L176 114" stroke={MUTED} strokeWidth="1.5" strokeDasharray="3 5" opacity="0.6" />

      {/* The target, unreached, with no edge arriving. */}
      <circle cx="212" cy="80" r="9" stroke={FAINT} strokeWidth="2" strokeDasharray="4 4" />

      <line x1="186" y1="62" x2="204" y2="98" stroke={DANGER} strokeWidth="2" strokeLinecap="round" />
      <line x1="204" y1="62" x2="186" y2="98" stroke={DANGER} strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

/** The package boundary, and the one edge that crosses it. */
export function BindingVisual({ className }: VisualProps) {
  return (
    <svg {...svgProps} className={className}>
      <rect x="14" y="34" width="94" height="92" rx="8" stroke={MUTED} strokeWidth="1.5" />
      <rect x="132" y="34" width="94" height="92" rx="8" stroke={MUTED} strokeWidth="1.5" strokeDasharray="5 4" />
      <text x="61" y="26" fill={MUTED} fontSize="10" fontFamily="ui-monospace, monospace" textAnchor="middle">
        your code
      </text>
      <text x="179" y="26" fill={MUTED} fontSize="10" fontFamily="ui-monospace, monospace" textAnchor="middle">
        node_modules
      </text>

      <circle cx="46" cy="62" r="5" fill={ACCENT} />
      <circle cx="46" cy="98" r="5" fill={FAINT} />
      <line x1="46" y1="62" x2="82" y2="80" stroke={ACCENT} strokeWidth="1.5" />
      <circle cx="86" cy="80" r="5" fill={ACCENT} />

      {/* The crossing: specifier resolved to the package's internal symbol. */}
      <line x1="86" y1="80" x2="160" y2="80" stroke={ACCENT} strokeWidth="2" strokeLinecap="round" />
      <circle cx="164" cy="80" r="5" fill={ACCENT} />
      <line x1="164" y1="80" x2="196" y2="102" stroke={ACCENT} strokeWidth="1.5" />
      <circle cx="200" cy="104" r="8" fill={DANGER} />
      <circle cx="196" cy="52" r="5" fill={FAINT} />
    </svg>
  );
}
