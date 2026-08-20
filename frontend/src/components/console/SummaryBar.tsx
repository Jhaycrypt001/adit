import type { ReportSummary } from "@/lib/report";
import type { ScanReport } from "@/lib/types";
import { BarList, SplitBar, type Segment } from "./charts";

function Panel({
  title,
  children,
  className = "",
}: {
  title: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-xl border border-border bg-card/40 p-4 ${className}`}>
      <h3 className="mb-3 text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
        {title}
      </h3>
      {children}
    </section>
  );
}

/**
 * The verdict, then the evidence.
 *
 * A responder wants one number before anything else — how many of these do I
 * have to act on today — so that is a hero number, not a tile in a row of five.
 * `unresolved` stays its own count rather than folding into either reachable
 * bucket: it means the search never ran, and reporting it as "not reachable"
 * would claim a search that never happened.
 */
export function SummaryBar({
  report,
  summary,
}: {
  report: ScanReport;
  summary: ReportSummary;
}) {
  const timings = Object.entries(report.timings ?? {}).sort((a, b) => b[1] - a[1]);

  const segments: Segment[] = [
    { label: "Reachable", value: summary.reachable, tone: "critical" },
    { label: "Unresolved", value: summary.unresolved, tone: "warning" },
    { label: "Not reachable", value: summary.notReachable, tone: "good" },
  ];

  const clear = summary.actionable === 0;

  return (
    <div className="flex flex-col gap-4">
      {/* Hero verdict */}
      <div
        className="rounded-xl border p-5"
        style={{
          borderColor: clear ? "var(--status-good)" : "var(--status-critical)",
          background: clear
            ? "color-mix(in oklch, var(--status-good) 8%, transparent)"
            : "color-mix(in oklch, var(--status-critical) 8%, transparent)",
        }}
      >
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="font-mono text-xs text-muted-foreground">{report.package}</p>
            <p className="mt-2 flex items-baseline gap-3">
              <span
                className="text-5xl font-semibold leading-none tabular-nums"
                style={{ color: clear ? "var(--status-good)" : "var(--status-critical)" }}
              >
                {summary.actionable}
              </span>
              <span className="text-lg font-medium">
                of {summary.total} need action
              </span>
            </p>
            <p className="mt-2 max-w-md text-sm leading-relaxed text-muted-foreground">
              {clear
                ? "Every advisory here was searched and none is callable from an entrypoint. That is a completed search, not an absence of data."
                : `${summary.reachable} reachable${summary.unresolved ? `, ${summary.unresolved} unresolved` : ""} — open the findings below for the exact call paths.`}
            </p>
          </div>
          <div className="text-right">
            <p className="font-mono text-xs text-muted-foreground">
              {report.elapsed.toFixed(2)}s
            </p>
            <p className="font-mono text-[11px] text-muted-foreground/70">
              {report.scan_id.slice(0, 12)}…
            </p>
          </div>
        </div>
      </div>

      {/* Evidence */}
      <div className="grid gap-3 lg:grid-cols-2">
        <Panel title="Outcome of every search" className="lg:col-span-2">
          <SplitBar segments={segments} />
        </Panel>

        <Panel title="Advisory class">
          <BarList
            tone="neutral"
            data={[
              { label: "runtime", value: summary.runtime },
              { label: "install-time", value: summary.installTime },
            ].filter((d) => d.value > 0)}
            emptyLabel="no advisories to classify"
          />
          <p className="mt-3 text-[11px] leading-relaxed text-muted-foreground">
            Install-time advisories are answered by blast radius, not
            reachability — the payload runs at install whether or not you call it.
          </p>
        </Panel>

        <Panel title="Severity, as the feed reports it">
          <BarList
            tone="neutral"
            data={summary.severities.map((s) => ({
              label: s.label.toLowerCase(),
              value: s.count,
            }))}
            emptyLabel="no severity data"
          />
          <p className="mt-3 text-[11px] leading-relaxed text-muted-foreground">
            OSV publishes CVSS vectors, not ratings. Grouped by vector version
            rather than scored here, because a wrong severity is worse than none.
          </p>
        </Panel>

        {timings.length > 0 && (
          <Panel title="Where the time went" className="lg:col-span-2">
            <BarList
              tone="neutral"
              data={timings.map(([stage, secs]) => ({
                label: stage,
                value: Number(secs.toFixed(2)),
                title: `${stage}: ${secs.toFixed(2)}s`,
              }))}
            />
          </Panel>
        )}
      </div>
    </div>
  );
}
