import { useState } from "react";
import { ApiError, whyReachable } from "../lib/api";
import type { WhyResult } from "../lib/types";

export function WhyPanel({ scanId }: { scanId: string | null }) {
  const [source, setSource] = useState("");
  const [target, setTarget] = useState("");
  const [result, setResult] = useState<WhyResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      setResult(
        await whyReachable(source.trim(), target.trim(), { scanId: scanId ?? undefined }),
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "lookup failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <p className="max-w-prose text-sm leading-relaxed text-muted-foreground">
        Exact symbol keys only. Unlike the MCP tool, this endpoint will not guess at a
        bare name &mdash; silently matching the wrong symbol over a public HTTP surface
        is a worse failure than making the caller be precise. Keys come from a prior
        scan&rsquo;s <span className="font-mono text-xs text-foreground">paths</span>.
      </p>

      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        <label className="flex flex-col gap-2 text-sm font-medium">
          source symbol key
          <input
            required
            disabled={loading}
            placeholder="sym:pkg@version:module#name"
            value={source}
            onChange={(e) => setSource(e.target.value)}
            className="rounded-lg border border-input bg-background px-3 py-2.5 font-mono text-sm outline-none transition focus:border-primary/60 focus:ring-1 focus:ring-primary/40 disabled:opacity-50"
          />
        </label>
        <label className="flex flex-col gap-2 text-sm font-medium">
          target symbol key
          <input
            required
            disabled={loading}
            placeholder="sym:pkg@version:module#name"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            className="rounded-lg border border-input bg-background px-3 py-2.5 font-mono text-sm outline-none transition focus:border-primary/60 focus:ring-1 focus:ring-primary/40 disabled:opacity-50"
          />
        </label>
        {scanId && (
          <p className="font-mono text-[11px] text-muted-foreground">
            scoped to scan_id {scanId}
          </p>
        )}
        <button
          type="submit"
          disabled={loading}
          className="self-start rounded-full bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground transition hover:bg-primary/90 disabled:opacity-50"
        >
          {loading ? "checking…" : "Why reachable"}
        </button>
        {error && <p className="text-sm text-destructive">{error}</p>}
      </form>

      {result && (
        <div className="rounded-xl border border-border bg-card/50 p-4">
          {result.reachable ? (
            <>
              <p className="text-sm font-semibold text-destructive">
                reachable &mdash; depth {result.depth}
              </p>
              <ol className="mt-3 flex flex-col gap-1 overflow-x-auto border-l-2 border-border pl-3">
                {result.path?.map((n, i) => (
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
            </>
          ) : (
            <>
              <p className="text-sm font-semibold text-emerald-400">not reachable</p>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                {result.explanation}
              </p>
            </>
          )}
        </div>
      )}
    </div>
  );
}
