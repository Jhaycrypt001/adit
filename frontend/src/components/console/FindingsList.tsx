import { useMemo, useState } from "react";
import type { Finding, PathNode, ScanReport } from "@/lib/types";
import { filterFindings, severityLabel, type StatusFilter } from "@/lib/report";
import { CopyButton } from "./CopyButton";
import { PathGraph } from "./charts";

const statusStyle: Record<Finding["status"], string> = {
  reachable: "bg-destructive/15 text-destructive ring-destructive/30",
  not_reachable: "bg-emerald-500/10 text-emerald-400 ring-emerald-500/25",
  unresolved: "bg-amber-500/10 text-amber-400 ring-amber-500/25",
};

const classStyle: Record<Finding["class"], string> = {
  install_time: "bg-primary/15 text-primary ring-primary/30",
  runtime: "bg-sky-500/10 text-sky-400 ring-sky-500/25",
  unknown: "bg-muted text-muted-foreground ring-border",
};

const FILTERS: { id: StatusFilter; label: string }[] = [
  { id: "actionable", label: "Actionable" },
  { id: "reachable", label: "Reachable" },
  { id: "unresolved", label: "Unresolved" },
  { id: "not_reachable", label: "Not reachable" },
  { id: "all", label: "All" },
];

function PathChain({
  nodes,
  onAskWhy,
}: {
  nodes: PathNode[];
  onAskWhy?: (source: string, target: string) => void;
}) {
  const first = nodes[0]?.key;
  const last = nodes[nodes.length - 1]?.key;
  return (
    <div className="rounded-lg border border-border bg-background/60 p-3">
      <PathGraph
        nodes={nodes.map((n, i) => ({
          label: n.name ?? "?",
          sub: n.file ? `${n.file}${n.line != null ? `:${n.line}` : ""}` : null,
          terminal: i === nodes.length - 1,
        }))}
      />
      {onAskWhy && first && last && (
        <button
          type="button"
          onClick={() => onAskWhy(first, last)}
          className="mt-3 rounded-full border border-border px-3 py-1 text-[11px] text-muted-foreground transition hover:border-primary/50 hover:text-foreground"
        >
          Open in Why reachable →
        </button>
      )}
    </div>
  );
}

function FindingCard({
  finding,
  onAskWhy,
  onBlast,
}: {
  finding: Finding;
  onAskWhy?: (source: string, target: string) => void;
  onBlast?: (spec: string) => void;
}) {
  const [open, setOpen] = useState(finding.actionable);

  return (
    <article className="overflow-hidden rounded-xl border border-border bg-card/40">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full flex-col gap-2 p-4 text-left transition hover:bg-muted/20"
      >
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-sm font-semibold">{finding.advisory_id}</span>
          <span className="font-mono text-xs text-muted-foreground">{finding.package}</span>
          <span
            className={`rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ${statusStyle[finding.status]}`}
          >
            {finding.status.replace("_", " ")}
          </span>
          <span
            className={`rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ${classStyle[finding.class]}`}
          >
            {finding.class.replace("_", " ")}
          </span>
          {finding.severity && (
            <span
              title={finding.severity}
              className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground"
            >
              {severityLabel(finding.severity).toLowerCase()}
            </span>
          )}
          <span className="ml-auto text-xs text-muted-foreground">{open ? "−" : "+"}</span>
        </div>
        <p className="text-sm leading-relaxed text-muted-foreground">{finding.summary}</p>
      </button>

      {open && (
        <div className="flex flex-col gap-4 border-t border-border p-4">
          {finding.reason && (
            <p className="text-sm italic leading-relaxed text-muted-foreground">
              {finding.reason}
            </p>
          )}

          {finding.severity && (
            <div className="rounded-lg border border-border bg-background/60 p-3">
              <p className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
                Severity, as the feed reports it
              </p>
              <p className="mt-1.5 break-all font-mono text-[11px] text-foreground">
                {finding.severity}
              </p>
            </div>
          )}

          {finding.symbol && (
            <div className="rounded-lg border border-border bg-background/60 p-3">
              <p className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
                Symbol resolution
              </p>
              <p className="mt-1.5 font-mono text-xs text-foreground">
                {finding.symbol.names.join(", ") || "—"}
              </p>
              <p className="mt-1 text-[11px] text-muted-foreground">
                tier {finding.symbol.tier} · confidence{" "}
                {finding.symbol.confidence.toFixed(2)} · {finding.symbol.method}
              </p>
            </div>
          )}

          {finding.paths.length > 0 ? (
            <div className="flex flex-col gap-3">
              <p className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
                {finding.paths.length} path{finding.paths.length === 1 ? "" : "s"}
              </p>
              {finding.paths.map((nodes, i) => (
                <PathChain key={i} nodes={nodes} onAskWhy={onAskWhy} />
              ))}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">
              No path returned for this advisory.
            </p>
          )}

          <div className="flex flex-wrap items-center gap-2">
            <CopyButton value={finding.advisory_id} label="Copy advisory id" />
            {onBlast && finding.package && (
              <button
                type="button"
                onClick={() => onBlast(finding.package)}
                className="rounded border border-border px-2 py-0.5 font-mono text-[10px] text-muted-foreground transition hover:border-primary/50 hover:text-foreground"
              >
                Blast radius →
              </button>
            )}
            {finding.blast_radius.length > 0 && (
              <span className="text-[11px] text-muted-foreground">
                {finding.blast_radius.length} known dependents
              </span>
            )}
          </div>
        </div>
      )}
    </article>
  );
}

export function FindingsList({
  report,
  onAskWhy,
  onBlast,
}: {
  report: ScanReport;
  onAskWhy?: (source: string, target: string) => void;
  onBlast?: (spec: string) => void;
}) {
  const [status, setStatus] = useState<StatusFilter>("actionable");
  const [query, setQuery] = useState("");

  const shown = useMemo(
    () => filterFindings(report.findings, status, query),
    [report.findings, status, query],
  );

  const counts = useMemo(
    () =>
      Object.fromEntries(
        FILTERS.map((f) => [f.id, filterFindings(report.findings, f.id, "").length]),
      ) as Record<StatusFilter, number>,
    [report.findings],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        {FILTERS.map((f) => (
          <button
            key={f.id}
            type="button"
            onClick={() => setStatus(f.id)}
            className={`rounded-full border px-3 py-1 text-xs transition ${
              status === f.id
                ? "border-primary/60 bg-primary/10 text-foreground"
                : "border-border text-muted-foreground hover:text-foreground"
            }`}
          >
            {f.label}
            <span className="ml-1.5 tabular-nums opacity-60">{counts[f.id] ?? 0}</span>
          </button>
        ))}
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Filter by id, package, symbol…"
          className="ml-auto min-w-[12rem] flex-1 rounded-full border border-input bg-background px-3 py-1.5 text-xs outline-none transition focus:border-primary/60 sm:flex-none"
        />
      </div>

      {shown.length === 0 ? (
        <p className="rounded-lg border border-border bg-muted/20 p-4 text-sm text-muted-foreground">
          {report.findings.length === 0
            ? "No advisories affect this repository's resolved dependencies. That is a real result, not an empty state."
            : "No findings match this filter."}
        </p>
      ) : (
        <div className="flex flex-col gap-3">
          {shown.map((f) => (
            <FindingCard
              key={f.advisory_id + f.package}
              finding={f}
              onAskWhy={onAskWhy}
              onBlast={onBlast}
            />
          ))}
        </div>
      )}
    </div>
  );
}
