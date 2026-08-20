import { useEffect, useRef, useState } from "react";
import { ApiError, scanRepo } from "@/lib/api";
import type { ScanReport } from "@/lib/types";

interface Props {
  onResult: (report: ScanReport) => void;
  disabled?: boolean;
}

const EXAMPLES = [
  { label: "expressjs/express", url: "https://github.com/expressjs/express" },
  { label: "sindresorhus/got", url: "https://github.com/sindresorhus/got" },
];

/** Rough stages, for a progress line during a request that has no streaming. */
const STAGES = [
  "cloning the repository",
  "installing dependencies (--ignore-scripts)",
  "parsing the code graph",
  "resolving the lockfile",
  "querying OSV",
  "binding symbols across the package boundary",
  "traversing",
];

export function ScanForm({ onResult, disabled = false }: Props) {
  const [repoUrl, setRepoUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stage, setStage] = useState(0);
  const [seconds, setSeconds] = useState(0);
  const abort = useRef<AbortController | null>(null);

  // `/scan` is one long synchronous request with no progress channel. Rather
  // than invent a fake percentage, this shows elapsed time and names the stage
  // the pipeline is most likely in -- clearly a guide, not a measurement.
  useEffect(() => {
    if (!loading) return;
    const started = Date.now();
    const id = window.setInterval(() => {
      const secs = Math.floor((Date.now() - started) / 1000);
      setSeconds(secs);
      setStage(Math.min(STAGES.length - 1, Math.floor(secs / 8)));
    }, 1000);
    return () => window.clearInterval(id);
  }, [loading]);

  useEffect(() => () => abort.current?.abort(), []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setStage(0);
    setSeconds(0);
    abort.current = new AbortController();
    try {
      onResult(await scanRepo(repoUrl.trim(), { signal: abort.current.signal }));
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        setError("Scan cancelled. The server may still be finishing it.");
      } else {
        setError(err instanceof ApiError ? err.message : "scan failed");
      }
    } finally {
      setLoading(false);
      abort.current = null;
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        <label htmlFor="scan-url" className="text-sm font-medium">
          GitHub repository URL
        </label>
        <input
          id="scan-url"
          type="url"
          required
          disabled={loading || disabled}
          placeholder="https://github.com/owner/repo"
          value={repoUrl}
          onChange={(e) => setRepoUrl(e.target.value)}
          className="rounded-lg border border-input bg-background px-3 py-2.5 font-mono text-sm outline-none transition focus:border-primary/60 focus:ring-1 focus:ring-primary/40 disabled:opacity-50"
        />
        <p className="text-[11px] leading-relaxed text-muted-foreground">
          Public repositories only, over https. The URL is validated against an
          allowlist before anything is cloned, and dependencies install with{" "}
          <span className="font-mono text-foreground">--ignore-scripts</span> so the
          repository&rsquo;s own code never runs.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
          Try
        </span>
        {EXAMPLES.map((ex) => (
          <button
            key={ex.url}
            type="button"
            disabled={loading || disabled}
            onClick={() => setRepoUrl(ex.url)}
            className="rounded-full border border-border px-3 py-1 font-mono text-[11px] text-muted-foreground transition hover:border-primary/50 hover:text-foreground disabled:opacity-50"
          >
            {ex.label}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="submit"
          disabled={loading || disabled || !repoUrl.trim()}
          className="rounded-full bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground transition hover:bg-primary/90 disabled:opacity-50"
        >
          {loading ? "Scanning…" : "Scan repository"}
        </button>
        {loading && (
          <button
            type="button"
            onClick={() => abort.current?.abort()}
            className="rounded-full border border-border px-4 py-2 text-xs text-muted-foreground transition hover:border-destructive/50 hover:text-foreground"
          >
            Cancel
          </button>
        )}
      </div>

      {loading && (
        <div className="rounded-lg border border-border bg-muted/20 p-4">
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm text-foreground">{STAGES[stage]}…</p>
            <span className="font-mono text-xs tabular-nums text-muted-foreground">
              {seconds}s
            </span>
          </div>
          <div className="mt-3 flex gap-1">
            {STAGES.map((_, i) => (
              <span
                key={i}
                className={`h-1 flex-1 rounded-full ${i <= stage ? "bg-primary/70" : "bg-border"}`}
              />
            ))}
          </div>
          <p className="mt-3 text-[11px] leading-relaxed text-muted-foreground">
            A real repository usually takes 40&ndash;90 seconds. Stages are indicative:
            the endpoint returns one response at the end rather than streaming
            progress, so this is elapsed time, not measured completion.
          </p>
        </div>
      )}

      {error && (
        <p className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          {error}
        </p>
      )}
    </form>
  );
}
