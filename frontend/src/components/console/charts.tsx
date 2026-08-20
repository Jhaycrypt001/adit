import { useId, useState } from "react";

/**
 * The console's chart primitives.
 *
 * Deliberately small. The data here is a handful of counts, and the honest form
 * for a handful of counts is a hero number, one split bar, and a short row of
 * bars -- not a donut, and never two y-scales. Colour is applied last and only
 * where it carries state; identity always also carries a label, so nothing is
 * encoded by hue alone.
 */

export const STATUS = {
  critical: "var(--status-critical)",
  good: "var(--status-good)",
  warning: "var(--status-warning)",
  neutral: "var(--muted-foreground)",
} as const;

export type StatusTone = keyof typeof STATUS;

export interface Segment {
  label: string;
  value: number;
  tone: StatusTone;
}

/**
 * One horizontal stacked bar: the whole advisory set, split by outcome.
 *
 * A 2px surface gap sits between segments so adjacent fills never touch. The
 * spacer is what keeps two similar hues readable for a colourblind reader, and
 * is why the validated palette's ΔE-7.9 pair is allowed here at all.
 */
export function SplitBar({ segments }: { segments: Segment[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const total = segments.reduce((s, x) => s + x.value, 0);
  const shown = segments.filter((s) => s.value > 0);

  if (total === 0) {
    return (
      <p className="rounded-lg border border-border bg-muted/20 p-3 text-xs text-muted-foreground">
        Nothing to split: no advisories affect this repository.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex h-3 w-full gap-[2px] overflow-hidden rounded-full">
        {shown.map((s, i) => (
          <div
            key={s.label}
            onMouseEnter={() => setHover(i)}
            onMouseLeave={() => setHover(null)}
            title={`${s.label}: ${s.value} of ${total}`}
            style={{
              width: `${(s.value / total) * 100}%`,
              background: STATUS[s.tone],
              opacity: hover === null || hover === i ? 1 : 0.45,
            }}
            className="h-full rounded-[2px] transition-opacity first:rounded-l-full last:rounded-r-full"
          />
        ))}
      </div>

      {/* Legend doubles as the direct labels, so identity is never colour alone. */}
      <ul className="flex flex-wrap items-center gap-x-5 gap-y-1.5">
        {shown.map((s) => (
          <li key={s.label} className="flex items-center gap-2">
            <span
              aria-hidden
              className="h-2 w-2 shrink-0 rounded-full"
              style={{ background: STATUS[s.tone] }}
            />
            <span className="text-xs text-muted-foreground">
              {s.label}
              <span className="ml-1.5 font-mono tabular-nums text-foreground">{s.value}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export interface BarDatum {
  label: string;
  value: number;
  title?: string;
}

/** A short row of horizontal bars. Values sit at the end of each bar rather
 *  than on an axis, because at this cardinality an axis is noise. */
export function BarList({
  data,
  tone = "neutral",
  emptyLabel = "nothing to show",
}: {
  data: BarDatum[];
  tone?: StatusTone;
  emptyLabel?: string;
}) {
  if (data.length === 0) {
    return <p className="text-xs text-muted-foreground">{emptyLabel}</p>;
  }
  const max = Math.max(...data.map((d) => d.value), 1);

  return (
    <ul className="flex flex-col gap-2">
      {data.map((d) => (
        <li key={d.label} className="flex items-center gap-3" title={d.title ?? d.label}>
          <span className="w-24 shrink-0 truncate font-mono text-[11px] text-muted-foreground">
            {d.label}
          </span>
          <span className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
            <span
              className="block h-full rounded-full"
              style={{ width: `${(d.value / max) * 100}%`, background: STATUS[tone] }}
            />
          </span>
          <span className="w-8 shrink-0 text-right font-mono text-[11px] tabular-nums text-foreground">
            {d.value}
          </span>
        </li>
      ))}
    </ul>
  );
}

export interface GraphNode {
  label: string;
  sub?: string | null;
  terminal?: boolean;
}

/**
 * A call path drawn as a node-link chain rather than an indented list.
 *
 * The path is the product's whole claim, so it gets a real figure: each hop is
 * a node, the last one is marked as the vulnerable symbol, and the file:line
 * that a reader would open sits directly under it.
 */
export function PathGraph({ nodes }: { nodes: GraphNode[] }) {
  const gid = useId();
  if (nodes.length === 0) return null;

  const ROW = 54;
  const height = nodes.length * ROW + 8;

  return (
    <svg
      viewBox={`0 0 480 ${height}`}
      // Anchored left, not centred. The default xMidYMid letterboxes a
      // fixed-aspect viewBox inside a wider container, which pushed the whole
      // chain into the middle of the card with a large empty gutter beside it.
      preserveAspectRatio="xMinYMid meet"
      className="w-full"
      style={{ maxHeight: height }}
      role="img"
      aria-label={`Call path: ${nodes.map((n) => n.label).join(" then ")}`}
    >
      <defs>
        <linearGradient id={`${gid}-edge`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--status-warning)" stopOpacity="0.9" />
          <stop offset="100%" stopColor="var(--status-critical)" stopOpacity="0.9" />
        </linearGradient>
      </defs>

      {nodes.map((n, i) => {
        const y = i * ROW + 20;
        const isLast = i === nodes.length - 1;
        const colour = isLast ? "var(--status-critical)" : "var(--primary)";
        return (
          <g key={i}>
            {!isLast && (
              <line
                x1="16"
                y1={y + 9}
                x2="16"
                y2={y + ROW - 9}
                stroke={`url(#${gid}-edge)`}
                strokeWidth="2"
                strokeLinecap="round"
              />
            )}
            <circle cx="16" cy={y} r={isLast ? 7 : 5} fill={colour} />
            {isLast && (
              <circle cx="16" cy={y} r="11" fill="none" stroke={colour} strokeWidth="1.5" opacity="0.45" />
            )}
            <text
              x="36"
              y={y + 4}
              fill="var(--foreground)"
              fontSize="13"
              fontFamily="ui-monospace, monospace"
            >
              {n.label}
            </text>
            {isLast && (
              <text
                x={36 + Math.min(n.label.length, 28) * 7.6 + 12}
                y={y + 4}
                fill="var(--status-critical)"
                fontSize="11"
                fontFamily="var(--font-sans)"
              >
                vulnerable
              </text>
            )}
            {n.sub && (
              <text
                x="36"
                y={y + 20}
                fill="var(--muted-foreground)"
                fontSize="11"
                fontFamily="ui-monospace, monospace"
              >
                {n.sub}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

/**
 * Blast radius as concentric rings: the compromised release at the centre, its
 * transitive dependents fanned around it, capped so a large set degrades into a
 * count instead of an unreadable hairball.
 */
export function RadiusGraph({
  centre,
  dependents,
  exposed,
}: {
  centre: string;
  dependents: string[];
  exposed: number;
}) {
  const MAX = 18;
  const shown = dependents.slice(0, MAX);
  const hidden = dependents.length - shown.length;
  const R = 74;

  return (
    <div className="flex flex-col items-center gap-3">
      <svg viewBox="0 0 240 200" className="w-full max-w-[320px]" role="img"
        aria-label={`${dependents.length} packages transitively depend on ${centre}`}>
        <circle cx="120" cy="100" r={R} fill="none" stroke="var(--border)" strokeWidth="1.5" />
        <circle cx="120" cy="100" r={R * 0.55} fill="none" stroke="var(--border)" strokeWidth="1.5" />

        {shown.map((d, i) => {
          const a = (i / Math.max(shown.length, 1)) * Math.PI * 2 - Math.PI / 2;
          const r = i % 2 === 0 ? R : R * 0.55;
          const x = 120 + r * Math.cos(a);
          const y = 100 + r * Math.sin(a);
          return (
            <g key={d}>
              <line x1="120" y1="100" x2={x} y2={y} stroke="var(--primary)" strokeWidth="1" opacity="0.28" />
              <circle cx={x} cy={y} r="4" fill="var(--primary)" opacity="0.8">
                <title>{d}</title>
              </circle>
            </g>
          );
        })}

        <circle cx="120" cy="100" r="9" fill={exposed > 0 ? STATUS.critical : STATUS.warning} />
        <circle
          cx="120"
          cy="100"
          r="14"
          fill="none"
          stroke={exposed > 0 ? STATUS.critical : STATUS.warning}
          strokeWidth="1.5"
          opacity="0.45"
        />
      </svg>
      <p className="text-center text-xs text-muted-foreground">
        <span className="font-mono text-foreground">{centre}</span>
        {" · "}
        {dependents.length} transitive dependent{dependents.length === 1 ? "" : "s"}
        {hidden > 0 && `, ${shown.length} drawn`}
      </p>
    </div>
  );
}
