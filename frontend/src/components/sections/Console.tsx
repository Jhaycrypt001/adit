import { useState } from "react";
import { HealthBadge } from "@/components/HealthBadge";
import { ScanForm } from "@/components/ScanForm";
import { ScanResults } from "@/components/ScanResults";
import { BlastPanel } from "@/components/BlastPanel";
import { WhyPanel } from "@/components/WhyPanel";
import type { ScanReport } from "@/lib/types";

type Tab = "scan" | "blast" | "why";

const TABS: { id: Tab; label: string }[] = [
  { id: "scan", label: "Scan" },
  { id: "blast", label: "Blast radius" },
  { id: "why", label: "Why reachable" },
];

/**
 * The working surface, over the same three endpoints the CLI and MCP server
 * wrap. A successful scan threads its `scan_id` into the other two tabs, so a
 * follow-up question stays inside that scan's isolated id namespace rather than
 * querying a shared one that a hosted deployment never writes to.
 */
export function Console({ onBack }: { onBack: () => void }) {
  const [tab, setTab] = useState<Tab>("scan");
  const [report, setReport] = useState<ScanReport | null>(null);

  return (
    <div className="min-h-screen w-full bg-background">
      <div className="mx-auto flex max-w-3xl flex-col gap-7 px-6 pb-40 pt-12 sm:px-8">
        <header className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <button
              type="button"
              onClick={onBack}
              className="mb-2 text-xs text-muted-foreground transition hover:text-foreground"
            >
              &larr; Back
            </button>
            <h1 className="text-2xl font-semibold tracking-tight">Console</h1>
          </div>
          <HealthBadge />
        </header>

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

        <main>
          {tab === "scan" && (
            <div className="flex flex-col gap-7">
              <ScanForm onResult={setReport} />
              {report && <ScanResults report={report} />}
            </div>
          )}
          {tab === "blast" && <BlastPanel scanId={report?.scan_id ?? null} />}
          {tab === "why" && <WhyPanel scanId={report?.scan_id ?? null} />}
        </main>
      </div>
    </div>
  );
}
