import { useState } from "react";
import { ApiError, getBlastRadius } from "@/lib/api";
import type { BlastResult } from "@/lib/types";
import type { ReportSummary } from "@/lib/report";
import { CopyButton } from "./CopyButton";
import { RadiusGraph } from "./charts";

interface Props {
  scanId: string | null;
  summary: ReportSummary | null;
  /** Prefilled when the user arrives by clicking a package in the results. */
  initialSpec?: string;
}

/** `rel:npm:lodash@4.17.20` and `pkg:npm:lodash` both appear in results; the
 *  endpoint wants the bare `name@version` it can rebuild a release key from. */
function toSpec(raw: string): string {
  const s = raw.trim();
  const m = /^rel:[^:]+:(.+)$/.exec(s);
  return m ? m[1] : s;
}

export function BlastPanel({ scanId, summary, initialSpec = "" }: Props) {
  const [spec, setSpec] = useState(initialSpec);
  const [maxLen, setMaxLen] = useState(10);
  const [result, setResult] = useState<BlastResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      setResult(await getBlastRadius(toSpec(spec), { maxLen, scanId: scanId ?? undefined }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "lookup failed");
    } finally {
      setLoading(false);
    }
  }

  const options = summary?.packages ?? [];

  return (
    <div className="flex flex-col gap-6">
      <p className="max-w-prose text-sm leading-relaxed text-muted-foreground">
        For an install-time compromise, reachability is meaningless: the payload
        ran at <span className="font-mono text-xs text-foreground">npm install</span>{" "}
        whether anything imported it or not. This is the query that matters instead:
        the transitive dependent set, and which of your services actually resolved it.
      </p>

      <form onSubmit={submit} className="flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          <label htmlFor="blast-spec" className="text-sm font-medium">
            package@version
          </label>
          <input
            id="blast-spec"
            required
            disabled={loading}
            list="blast-packages"
            placeholder="lodash@4.17.20"
            value={spec}
            onChange={(e) => setSpec(e.target.value)}
            className="rounded-lg border border-input bg-background px-3 py-2.5 font-mono text-sm outline-none transition focus:border-primary/60 focus:ring-1 focus:ring-primary/40 disabled:opacity-50"
          />
          <datalist id="blast-packages">
            {options.map((p) => (
              <option key={p} value={p} />
            ))}
          </datalist>

          {options.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              <span className="py-1 text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
                From this scan
              </span>
              {options.slice(0, 8).map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => setSpec(p)}
                  className="rounded-full border border-border px-2.5 py-1 font-mono text-[11px] text-muted-foreground transition hover:border-primary/50 hover:text-foreground"
                >
                  {p}
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="flex flex-wrap items-end gap-4">
          <label className="flex flex-col gap-1.5 text-xs text-muted-foreground">
            Max depth
            <input
              type="number"
              min={1}
              max={30}
              value={maxLen}
              disabled={loading}
              onChange={(e) => setMaxLen(Math.max(1, Math.min(30, Number(e.target.value) || 1)))}
              className="w-20 rounded-lg border border-input bg-background px-3 py-2 font-mono text-sm outline-none focus:border-primary/60 disabled:opacity-50"
            />
          </label>
          <button
            type="submit"
            disabled={loading || !spec.trim()}
            className="rounded-full bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground transition hover:bg-primary/90 disabled:opacity-50"
          >
            {loading ? "Querying…" : "Blast radius"}
          </button>
        </div>

        {scanId ? (
          <p className="font-mono text-[11px] text-muted-foreground">
            scoped to scan_id {scanId.slice(0, 12)}…
          </p>
        ) : (
          <p className="text-[11px] text-muted-foreground">
            No scan in this session, so this queries the unscoped namespace, which
            is empty on a hosted deployment. Run a scan first for meaningful results.
          </p>
        )}
        {error && <p className="text-sm text-destructive">{error}</p>}
      </form>

      {result && (
        <div className="flex flex-col gap-4">
          <div className="grid grid-cols-2 gap-2">
            <div className="rounded-lg border border-border bg-card/40 px-4 py-3">
              <span className="text-2xl font-semibold tabular-nums">
                {result.dependent_packages.length}
              </span>
              <p className="mt-1 text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
                Dependent packages
              </p>
            </div>
            <div className="rounded-lg border border-border bg-card/40 px-4 py-3">
              <span
                className={`text-2xl font-semibold tabular-nums ${result.exposed_services.length ? "text-destructive" : "text-emerald-400"}`}
              >
                {result.exposed_services.length}
              </span>
              <p className="mt-1 text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
                Exposed services
              </p>
            </div>
          </div>

          {result.dependent_packages.length === 0 && result.exposed_services.length === 0 && (
            <p className="rounded-lg border border-border bg-muted/20 p-4 text-sm leading-relaxed text-muted-foreground">
              Nothing in this scan transitively depends on{" "}
              <span className="font-mono text-foreground">{result.package}</span>. That is
              a real answer, not an empty state. The traversal ran and found no
              path.
            </p>
          )}

          {result.exposed_services.length > 0 && (
            <section className="rounded-xl border border-border bg-card/40 p-4">
              <h3 className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                Exposed services
              </h3>
              <ul className="mt-3 flex flex-col divide-y divide-border">
                {result.exposed_services.map((s, i) => (
                  <li key={i} className="flex flex-wrap items-baseline gap-x-3 py-2">
                    <span className="font-mono text-xs text-foreground">{s.service}</span>
                    <span className="font-mono text-[11px] text-muted-foreground">
                      source {s.source}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {result.dependent_packages.length > 0 && (
            <section className="rounded-xl border border-border bg-card/40 p-4">
              <h3 className="mb-3 text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                Reverse transitive closure
              </h3>
              <RadiusGraph
                centre={result.package}
                dependents={result.dependent_packages}
                exposed={result.exposed_services.length}
              />
            </section>
          )}

          {result.dependent_packages.length > 0 && (
            <section className="rounded-xl border border-border bg-card/40 p-4">
              <div className="flex items-center justify-between gap-3">
                <h3 className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                  Dependent packages
                </h3>
                <CopyButton
                  value={result.dependent_packages.join("\n")}
                  label="Copy all"
                />
              </div>
              <ul className="mt-3 flex max-h-72 flex-col gap-0.5 overflow-y-auto font-mono text-[11px] text-muted-foreground">
                {result.dependent_packages.map((k) => (
                  <li key={k} className="truncate" title={k}>
                    {k}
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
