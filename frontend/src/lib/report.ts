import type { Finding, ScanReport } from "./types";

/** Everything the console derives from a report, computed once. */
export interface ReportSummary {
  total: number;
  actionable: number;
  reachable: number;
  notReachable: number;
  unresolved: number;
  installTime: number;
  runtime: number;
  severities: { label: string; count: number }[];
  /** Distinct `package@version` strings, for the blast-radius picker. */
  packages: string[];
  /** Distinct symbol keys seen anywhere in any path, for the why picker. */
  symbols: SymbolOption[];
}

export interface SymbolOption {
  key: string;
  label: string;
  /** True for the last node of a path — i.e. a vulnerable symbol. */
  isTarget: boolean;
}

const SEVERITY_ORDER = ["CRITICAL", "HIGH", "MODERATE", "MEDIUM", "LOW", "UNKNOWN"];

/**
 * OSV's `severity` is usually a CVSS *vector*, not a word.
 *
 * Rendering the raw string produced chips reading
 * `cvss:4.0/av:n/ac:l/at:n/pr:n/...` — accurate and unreadable. Computing a
 * qualitative rating from the vector is not something to fake: v3.1 scoring is
 * implementable but v4.0 is materially different, and a wrong severity on a
 * security tool is worse than no severity. So a vector is labelled by its CVSS
 * version and the full string is kept for the tooltip; only an actual
 * qualitative word from the feed is shown as one.
 */
export function severityLabel(raw: string): string {
  const s = (raw || "").trim();
  if (!s) return "UNKNOWN";
  const cvss = /^cvss:(\d+\.\d+)/i.exec(s);
  if (cvss) return `CVSS ${cvss[1]}`;
  if (/^[A-Za-z]+$/.test(s)) return s.toUpperCase();
  return "UNKNOWN";
}

export function summarise(report: ScanReport): ReportSummary {
  const sev = new Map<string, number>();
  const packages = new Set<string>();
  const symbols = new Map<string, SymbolOption>();

  let reachable = 0;
  let notReachable = 0;
  let unresolved = 0;
  let installTime = 0;
  let runtime = 0;

  for (const f of report.findings) {
    if (f.status === "reachable") reachable++;
    else if (f.status === "not_reachable") notReachable++;
    else unresolved++;

    if (f.class === "install_time") installTime++;
    else if (f.class === "runtime") runtime++;

    const s = severityLabel(f.severity);
    sev.set(s, (sev.get(s) ?? 0) + 1);

    if (f.package) packages.add(f.package);

    for (const path of f.paths) {
      path.forEach((node, i) => {
        if (!node.key) return;
        const isTarget = i === path.length - 1;
        const existing = symbols.get(node.key);
        // A key that is ever a target stays flagged as one; it may appear
        // mid-path in some other finding.
        if (existing) {
          if (isTarget) existing.isTarget = true;
          return;
        }
        symbols.set(node.key, {
          key: node.key,
          label: node.name ?? node.key,
          isTarget,
        });
      });
    }
  }

  const severities = [...sev.entries()]
    .sort((a, b) => {
      const ai = SEVERITY_ORDER.indexOf(a[0]);
      const bi = SEVERITY_ORDER.indexOf(b[0]);
      return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
    })
    .map(([label, count]) => ({ label, count }));

  return {
    total: report.findings.length,
    actionable: report.findings.filter((f) => f.actionable).length,
    reachable,
    notReachable,
    unresolved,
    installTime,
    runtime,
    severities,
    packages: [...packages].sort(),
    symbols: [...symbols.values()].sort((a, b) => a.label.localeCompare(b.label)),
  };
}

export type StatusFilter = "all" | "actionable" | Finding["status"];

export function filterFindings(
  findings: Finding[],
  status: StatusFilter,
  query: string,
): Finding[] {
  const q = query.trim().toLowerCase();
  return findings.filter((f) => {
    if (status === "actionable" && !f.actionable) return false;
    if (status !== "all" && status !== "actionable" && f.status !== status) return false;
    if (!q) return true;
    return (
      f.advisory_id.toLowerCase().includes(q) ||
      f.package.toLowerCase().includes(q) ||
      f.summary.toLowerCase().includes(q) ||
      (f.symbol?.names ?? []).some((n) => n.toLowerCase().includes(q))
    );
  });
}

/** The report as the CLI would have printed it, for pasting into a ticket. */
export function toPlainText(report: ScanReport): string {
  const lines: string[] = [
    `${report.package}`,
    `${report.headline}`,
    `scan_id ${report.scan_id} · ${report.elapsed.toFixed(2)}s`,
    "",
  ];
  for (const f of report.findings) {
    lines.push(
      `${f.actionable ? "x" : "·"} ${f.advisory_id}  ${f.package}  [${f.status}/${f.class}${f.severity ? `/${f.severity}` : ""}]`,
    );
    if (f.summary) lines.push(`    ${f.summary}`);
    if (f.reason) lines.push(`    reason: ${f.reason}`);
    for (const path of f.paths) {
      lines.push(
        "    " +
          path
            .map((n) => `${n.name ?? "?"}${n.file ? ` (${n.file}${n.line != null ? `:${n.line}` : ""})` : ""}`)
            .join(" -> "),
      );
    }
    lines.push("");
  }
  return lines.join("\n");
}
