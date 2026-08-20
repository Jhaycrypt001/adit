import { useEffect, useRef, useState } from "react";
import { ApiError, scanRepo, suggestedSubdirs } from "@/lib/api";
import type { ScanReport } from "@/lib/types";

interface Props {
  onResult: (report: ScanReport) => void;
  disabled?: boolean;
  /** Collapsed once results exist, so the dashboard is what you see first. */
  compact?: boolean;
}

const EXAMPLES = [
  { label: "expressjs/express", url: "https://github.com/expressjs/express", subdir: "" },
  { label: "sindresorhus/got", url: "https://github.com/sindresorhus/got", subdir: "" },
  {
    label: "Jhaycrypt001/adit /frontend",
    url: "https://github.com/Jhaycrypt001/adit",
    subdir: "frontend",
  },
];

const STAGES = [
  "cloning the repository",
  "installing dependencies (--ignore-scripts)",
  "parsing the code graph",
  "resolving the lockfile",
  "querying OSV",
  "binding symbols across the package boundary",
  "traversing",
];

export function ScanForm({ onResult, disabled = false, compact = false }: Props) {
  const [repoUrl, setRepoUrl] = useState("");
  const [subdir, setSubdir] = useState("");
  const [open, setOpen] = useState(!compact);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [stage, setStage] = useState(0);
  const [seconds, setSeconds] = useState(0);
  const abort = useRef<AbortController | null>(null);

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

  // Collapse on the transition into compact, not inside submit(): at the moment
  // the first scan is submitted there are still zero results, so `compact` is
  // false and a collapse there would never fire. Tracking the edge also means
  // re-opening it by hand afterwards sticks.
  const wasCompact = useRef(compact);
  useEffect(() => {
    if (compact && !wasCompact.current) setOpen(false);
    wasCompact.current = compact;
  }, [compact]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setSuggestions([]);
    setStage(0);
    setSeconds(0);
    abort.current = new AbortController();
    try {
      const report = await scanRepo(repoUrl.trim(), {
        subdir,
        signal: abort.current.signal,
      });
      onResult(report);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        setError("Scan cancelled. The server may still be finishing it.");
      } else if (err instanceof ApiError) {
        setError(err.message);
        // The server names the subdirectories it found; make them clickable
        // rather than making the user retype one.
        setSuggestions(suggestedSubdirs(err.message));
      } else {
        setError("scan failed");
      }
    } finally {
      setLoading(false);
      abort.current = null;
    }
  }

  if (compact && !open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        disabled={disabled}
        className="flex w-full items-center justify-between gap-3 rounded-xl border border-border bg-card/40 px-4 py-3 text-left transition hover:border-primary/50 disabled:opacity-50"
      >
        <span className="text-sm font-medium">Scan another repository</span>
        <span className="text-xs text-muted-foreground">+</span>
      </button>
    );
  }

  return (
    <form
      onSubmit={submit}
      className={compact ? "flex flex-col gap-4 rounded-xl border border-border bg-card/40 p-4" : "flex flex-col gap-4"}
    >
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
      </div>

      <div className="flex flex-col gap-2">
        <label htmlFor="scan-subdir" className="text-sm font-medium">
          Subfolder <span className="font-normal text-muted-foreground">(optional)</span>
        </label>
        <input
          id="scan-subdir"
          disabled={loading || disabled}
          placeholder="frontend"
          value={subdir}
          onChange={(e) => setSubdir(e.target.value)}
          className="rounded-lg border border-input bg-background px-3 py-2.5 font-mono text-sm outline-none transition focus:border-primary/60 focus:ring-1 focus:ring-primary/40 disabled:opacity-50"
        />
        <p className="text-[11px] leading-relaxed text-muted-foreground">
          Only needed when <span className="font-mono text-foreground">package.json</span> is
          not at the repository root: a monorepo, or a frontend beside a backend in
          another language.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
          Try
        </span>
        {EXAMPLES.map((ex) => (
          <button
            key={ex.label}
            type="button"
            disabled={loading || disabled}
            onClick={() => {
              setRepoUrl(ex.url);
              setSubdir(ex.subdir);
            }}
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
        {compact && !loading && (
          <button
            type="button"
            onClick={() => setOpen(false)}
            className="text-xs text-muted-foreground transition hover:text-foreground"
          >
            Close
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
            the endpoint returns one response at the end rather than streaming progress.
          </p>
        </div>
      )}

      {error && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-3">
          <p className="text-sm text-destructive">{error}</p>
          {suggestions.length > 0 && (
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <span className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
                Scan instead
              </span>
              {suggestions.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => {
                    setSubdir(s);
                    setError(null);
                    setSuggestions([]);
                  }}
                  className="rounded-full border border-border px-3 py-1 font-mono text-[11px] text-foreground transition hover:border-primary/50"
                >
                  {s}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </form>
  );
}
