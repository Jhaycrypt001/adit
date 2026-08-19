import type { Finding, PathNode } from "../lib/types";

function PathChain({ nodes }: { nodes: PathNode[] }) {
  return (
    <ol className="flex flex-col gap-1 border-l-2 border-border pl-3 text-sm">
      {nodes.map((n, i) => (
        <li key={i} className="font-mono text-xs">
          <span className="text-foreground">{n.name ?? "?"}</span>
          {n.file && (
            <span className="text-muted-foreground">
              {" "}
              &mdash; {n.file}
              {n.line != null ? `:${n.line}` : ""}
            </span>
          )}
        </li>
      ))}
    </ol>
  );
}

const statusStyle: Record<Finding["status"], string> = {
  reachable: "bg-destructive/15 text-destructive ring-1 ring-destructive/30",
  not_reachable: "bg-emerald-500/10 text-emerald-400 ring-1 ring-emerald-500/25",
  unresolved: "bg-amber-500/10 text-amber-400 ring-1 ring-amber-500/25",
};

const classStyle: Record<Finding["class"], string> = {
  install_time: "bg-primary/15 text-primary ring-1 ring-primary/30",
  runtime: "bg-sky-500/10 text-sky-400 ring-1 ring-sky-500/25",
  unknown: "bg-muted text-muted-foreground ring-1 ring-border",
};

export function FindingCard({ finding }: { finding: Finding }) {
  return (
    <article className="flex flex-col gap-3 rounded-xl border border-border bg-card/50 p-4">
      <header className="flex flex-wrap items-center gap-2">
        <h3 className="font-mono text-sm font-semibold">{finding.advisory_id}</h3>
        <span className="font-mono text-xs text-muted-foreground">{finding.package}</span>
        <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${statusStyle[finding.status]}`}>
          {finding.status.replace("_", " ")}
        </span>
        <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${classStyle[finding.class]}`}>
          {finding.class.replace("_", " ")}
        </span>
        {finding.severity && (
          <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
            {finding.severity}
          </span>
        )}
        {finding.actionable && (
          <span className="rounded-full bg-foreground px-2 py-0.5 text-[11px] font-semibold text-background">
            actionable
          </span>
        )}
      </header>

      <p className="text-sm leading-relaxed">{finding.summary}</p>

      {finding.reason && (
        <p className="text-sm italic leading-relaxed text-muted-foreground">{finding.reason}</p>
      )}

      {finding.symbol && (
        <p className="font-mono text-[11px] text-muted-foreground">
          symbol: {finding.symbol.names.join(", ")} &middot; tier {finding.symbol.tier} &middot;
          confidence {finding.symbol.confidence.toFixed(2)} &middot; {finding.symbol.method}
        </p>
      )}

      {finding.paths.length > 0 && (
        <div className="flex flex-col gap-3 overflow-x-auto">
          {finding.paths.map((nodes, i) => (
            <PathChain key={i} nodes={nodes} />
          ))}
        </div>
      )}

      {finding.blast_radius.length > 0 && (
        <details className="text-sm">
          <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
            blast radius ({finding.blast_radius.length} dependents)
          </summary>
          <ul className="mt-2 flex max-h-56 flex-col gap-0.5 overflow-y-auto pl-4 font-mono text-[11px] text-muted-foreground">
            {finding.blast_radius.map((k) => (
              <li key={k}>{k}</li>
            ))}
          </ul>
        </details>
      )}
    </article>
  );
}
