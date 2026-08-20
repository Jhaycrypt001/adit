import type { ReportSummary } from "@/lib/report";
import type { ScanReport } from "@/lib/types";

function Stat({
  value,
  label,
  tone = "default",
}: {
  value: number | string;
  label: string;
  tone?: "default" | "danger" | "good" | "warn";
}) {
  const colour = {
    default: "text-foreground",
    danger: "text-destructive",
    good: "text-emerald-400",
    warn: "text-amber-400",
  }[tone];
  return (
    <div className="flex flex-col gap-1 rounded-lg border border-border bg-card/40 px-4 py-3">
      <span className={`text-2xl font-semibold leading-none tabular-nums ${colour}`}>
        {value}
      </span>
      <span className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
        {label}
      </span>
    </div>
  );
}

/**
 * The counts a responder reads first.
 *
 * `unresolved` gets its own tile rather than being folded into either reachable
 * bucket: it means the search never ran, and presenting that as "not reachable"
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

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 className="font-mono text-sm font-semibold">{report.package}</h2>
        <p className="font-mono text-[11px] text-muted-foreground">
          {report.elapsed.toFixed(2)}s · scan_id {report.scan_id.slice(0, 12)}…
        </p>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
        <Stat value={summary.total} label="Advisories" />
        <Stat
          value={summary.actionable}
          label="Actionable"
          tone={summary.actionable > 0 ? "danger" : "good"}
        />
        <Stat value={summary.reachable} label="Reachable" tone={summary.reachable ? "danger" : "default"} />
        <Stat value={summary.notReachable} label="Not reachable" tone="good" />
        <Stat
          value={summary.unresolved}
          label="Unresolved"
          tone={summary.unresolved ? "warn" : "default"}
        />
      </div>

      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-muted-foreground">
        {summary.severities.length > 0 && (
          <span className="flex flex-wrap items-center gap-2">
            <span className="uppercase tracking-[0.12em]">Severity</span>
            {summary.severities.map((s) => (
              <span
                key={s.label}
                className="rounded-full border border-border px-2 py-0.5 font-mono text-[11px]"
              >
                {s.label.toLowerCase()} {s.count}
              </span>
            ))}
            <span className="text-[11px] normal-case tracking-normal opacity-70">
              (vectors, not ratings &mdash; see each finding)
            </span>
          </span>
        )}
        <span className="flex items-center gap-2">
          <span className="uppercase tracking-[0.12em]">Class</span>
          <span className="rounded-full border border-border px-2 py-0.5 font-mono text-[11px]">
            runtime {summary.runtime}
          </span>
          <span className="rounded-full border border-border px-2 py-0.5 font-mono text-[11px]">
            install-time {summary.installTime}
          </span>
        </span>
      </div>

      {timings.length > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
            Stage timings
          </summary>
          <div className="mt-2 flex flex-col gap-1">
            {timings.map(([stage, secs]) => {
              const pct = report.elapsed > 0 ? Math.min(100, (secs / report.elapsed) * 100) : 0;
              return (
                <div key={stage} className="flex items-center gap-3">
                  <span className="w-28 shrink-0 font-mono text-[11px] text-muted-foreground">
                    {stage}
                  </span>
                  <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
                    <span
                      className="block h-full rounded-full bg-primary/70"
                      style={{ width: `${pct}%` }}
                    />
                  </span>
                  <span className="w-14 shrink-0 text-right font-mono text-[11px] tabular-nums text-muted-foreground">
                    {secs.toFixed(2)}s
                  </span>
                </div>
              );
            })}
          </div>
        </details>
      )}
    </div>
  );
}
