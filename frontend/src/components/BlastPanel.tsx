import { useState } from "react";
import { ApiError, getBlastRadius } from "../lib/api";
import type { BlastResult } from "../lib/types";

export function BlastPanel({ scanId }: { scanId: string | null }) {
  const [spec, setSpec] = useState("");
  const [result, setResult] = useState<BlastResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      setResult(await getBlastRadius(spec.trim(), { scanId: scanId ?? undefined }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "lookup failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <p className="max-w-prose text-sm leading-relaxed text-muted-foreground">
        For an install-time compromise, reachability is meaningless &mdash; the payload
        ran at <span className="font-mono text-xs text-foreground">npm install</span>{" "}
        whether anything imported it or not. This is the query that matters instead.
      </p>

      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        <label className="flex flex-col gap-2 text-sm font-medium">
          package@version
          <input
            required
            disabled={loading}
            placeholder="lodash@4.17.20"
            value={spec}
            onChange={(e) => setSpec(e.target.value)}
            className="rounded-lg border border-input bg-background px-3 py-2.5 font-mono text-sm outline-none transition focus:border-primary/60 focus:ring-1 focus:ring-primary/40 disabled:opacity-50"
          />
        </label>
        {scanId ? (
          <p className="font-mono text-[11px] text-muted-foreground">
            scoped to scan_id {scanId}
          </p>
        ) : (
          <p className="text-[11px] text-muted-foreground">
            No scan yet &mdash; this will query the unscoped namespace, which is empty
            on a hosted deployment. Run a scan first.
          </p>
        )}
        <button
          type="submit"
          disabled={loading}
          className="self-start rounded-full bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground transition hover:bg-primary/90 disabled:opacity-50"
        >
          {loading ? "looking up…" : "Blast radius"}
        </button>
        {error && <p className="text-sm text-destructive">{error}</p>}
      </form>

      {result && (
        <div className="grid gap-5 sm:grid-cols-2">
          <section className="rounded-xl border border-border bg-card/50 p-4">
            <h3 className="text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">
              Dependent packages ({result.dependent_packages.length})
            </h3>
            <ul className="mt-3 flex max-h-64 flex-col gap-0.5 overflow-y-auto font-mono text-[11px] text-muted-foreground">
              {result.dependent_packages.map((k) => (
                <li key={k}>{k}</li>
              ))}
            </ul>
          </section>
          <section className="rounded-xl border border-border bg-card/50 p-4">
            <h3 className="text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">
              Exposed services ({result.exposed_services.length})
            </h3>
            <ul className="mt-3 flex max-h-64 flex-col gap-0.5 overflow-y-auto font-mono text-[11px] text-muted-foreground">
              {result.exposed_services.map((s, i) => (
                <li key={i}>
                  {s.service} &mdash; {s.source}
                </li>
              ))}
            </ul>
          </section>
        </div>
      )}
    </div>
  );
}
