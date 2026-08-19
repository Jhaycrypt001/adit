import type { ScanReport } from "../lib/types";
import { FindingCard } from "./FindingCard";

export function ScanResults({ report }: { report: ScanReport }) {
  const actionable = report.findings.filter((f) => f.actionable);
  const clear = report.findings.filter((f) => !f.actionable);

  return (
    <div className="flex flex-col gap-5">
      <div className="rounded-xl border border-border bg-muted/20 p-4">
        <h2 className="font-mono text-sm font-semibold">{report.package}</h2>
        <p className="mt-1 text-sm text-muted-foreground">{report.headline}</p>
        <p className="mt-2 font-mono text-[11px] text-muted-foreground/70">
          scan_id {report.scan_id} &middot; {report.elapsed.toFixed(2)}s
        </p>
      </div>

      {actionable.length > 0 && (
        <section className="flex flex-col gap-3">
          <h3 className="text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">
            Actionable ({actionable.length})
          </h3>
          {actionable.map((f) => (
            <FindingCard key={f.advisory_id + f.package} finding={f} />
          ))}
        </section>
      )}

      {clear.length > 0 && (
        <details>
          <summary className="cursor-pointer text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground hover:text-foreground">
            Not reachable ({clear.length})
          </summary>
          <div className="mt-3 flex flex-col gap-3">
            {clear.map((f) => (
              <FindingCard key={f.advisory_id + f.package} finding={f} />
            ))}
          </div>
        </details>
      )}

      {report.findings.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No advisories affect this repository&rsquo;s resolved dependencies. That is a
          real result, not an empty state.
        </p>
      )}
    </div>
  );
}
