import { useCallback, useMemo, useState } from "react";
import { useHealth } from "@/hooks/use-health";
import { ApiOfflineNotice, ApiStatusBadge } from "@/components/console/ApiStatus";
import { ScanForm } from "@/components/console/ScanForm";
import { SummaryBar } from "@/components/console/SummaryBar";
import { FindingsList } from "@/components/console/FindingsList";
import { BlastPanel } from "@/components/console/BlastPanel";
import { WhyPanel } from "@/components/console/WhyPanel";
import { CopyButton } from "@/components/console/CopyButton";
import { summarise, toPlainText } from "@/lib/report";
import type { ScanReport } from "@/lib/types";

type Tab = "scan" | "blast" | "why";

const TABS: { id: Tab; label: string }[] = [
  { id: "scan", label: "Scan" },
  { id: "blast", label: "Blast radius" },
  { id: "why", label: "Why reachable" },
];

/**
 * The working surface, over the same three endpoints the CLI and MCP server
 * wrap.
 *
 * The three tabs are one workflow rather than three unrelated forms: a scan
 * produces the package specs and symbol keys the other two need, and handing
 * those across is what makes them usable at all. `/why` in particular takes
 * exact canonical keys and refuses to guess -- correct for a public API,
 * unusable as a UI unless the keys are offered rather than remembered.
 */
export function Console({ onBack }: { onBack: () => void }) {
  const [tab, setTab] = useState<Tab>("scan");
  const [report, setReport] = useState<ScanReport | null>(null);
  const [blastSpec, setBlastSpec] = useState("");
  const [why, setWhy] = useState<{ source: string; target: string }>({
    source: "",
    target: "",
  });

  const health = useHealth();
  const summary = useMemo(() => (report ? summarise(report) : null), [report]);

  const askWhy = useCallback((source: string, target: string) => {
    setWhy({ source, target });
    setTab("why");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  const askBlast = useCallback((spec: string) => {
    setBlastSpec(spec);
    setTab("blast");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  const downloadJson = useCallback(() => {
    if (!report) return;
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `adit-${report.package.replace(/[^a-z0-9.@-]/gi, "_")}-${report.scan_id.slice(0, 8)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }, [report]);

  const offline = health.state === "offline";

  return (
    <div className="min-h-screen w-full bg-background">
      <div className="mx-auto flex max-w-4xl flex-col gap-7 px-6 pb-40 pt-12 sm:px-8">
        <header className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <button
              type="button"
              onClick={onBack}
              className="mb-2 text-xs text-muted-foreground transition hover:text-foreground"
            >
              ← Back
            </button>
            <h1 className="text-2xl font-semibold tracking-tight">Console</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Scan a repository, then ask follow-up questions about that scan.
            </p>
          </div>
          <ApiStatusBadge health={health} />
        </header>

        {offline && <ApiOfflineNotice health={health} />}

        <nav className="flex gap-1 border-b border-border" role="tablist">
          {TABS.map((t) => (
            <button
              key={t.id}
              role="tab"
              aria-selected={tab === t.id}
              onClick={() => setTab(t.id)}
              className={`-mb-px border-b-2 px-3 py-2.5 text-sm font-medium transition ${
                tab === t.id
                  ? "border-primary text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              {t.label}
            </button>
          ))}
        </nav>

        <main className="flex flex-col gap-7">
          {tab === "scan" && (
            <>
              <ScanForm onResult={setReport} disabled={offline} />

              {report && summary && (
                <>
                  <div className="h-px bg-border" />
                  <SummaryBar report={report} summary={summary} />

                  <div className="flex flex-wrap items-center gap-2">
                    <CopyButton value={report.scan_id} label="Copy scan_id" />
                    <CopyButton value={toPlainText(report)} label="Copy as text" />
                    <button
                      type="button"
                      onClick={downloadJson}
                      className="rounded border border-border px-2 py-0.5 font-mono text-[10px] text-muted-foreground transition hover:border-primary/50 hover:text-foreground"
                    >
                      Download JSON
                    </button>
                  </div>

                  <FindingsList report={report} onAskWhy={askWhy} onBlast={askBlast} />
                </>
              )}
            </>
          )}

          {tab === "blast" && (
            <BlastPanel
              scanId={report?.scan_id ?? null}
              summary={summary}
              key={blastSpec}
              initialSpec={blastSpec}
            />
          )}

          {tab === "why" && (
            <WhyPanel
              scanId={report?.scan_id ?? null}
              summary={summary}
              key={`${why.source}|${why.target}`}
              initialSource={why.source}
              initialTarget={why.target}
            />
          )}
        </main>
      </div>
    </div>
  );
}
