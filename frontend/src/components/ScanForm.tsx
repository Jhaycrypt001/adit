import { useState } from "react";
import { ApiError, scanRepo } from "../lib/api";
import type { ScanReport } from "../lib/types";

interface Props {
  onResult: (report: ScanReport) => void;
}

/** A couple of repos that make the point quickly, since typing a URL from
 *  scratch is a poor first move on a tool nobody has used before. */
const EXAMPLES = [
  "https://github.com/expressjs/express",
  "https://github.com/sindresorhus/got",
];

export function ScanForm({ onResult }: Props) {
  const [repoUrl, setRepoUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      onResult(await scanRepo(repoUrl.trim()));
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "scan failed — is the API reachable?",
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3">
      <label className="flex flex-col gap-2 text-sm font-medium">
        GitHub repository URL
        <input
          type="url"
          required
          disabled={loading}
          placeholder="https://github.com/owner/repo"
          value={repoUrl}
          onChange={(e) => setRepoUrl(e.target.value)}
          className="rounded-lg border border-input bg-background px-3 py-2.5 font-mono text-sm outline-none transition focus:border-primary/60 focus:ring-1 focus:ring-primary/40 disabled:opacity-50"
        />
      </label>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-muted-foreground">try</span>
        {EXAMPLES.map((url) => (
          <button
            key={url}
            type="button"
            disabled={loading}
            onClick={() => setRepoUrl(url)}
            className="rounded-full border border-border px-3 py-1 font-mono text-[11px] text-muted-foreground transition hover:border-primary/50 hover:text-foreground disabled:opacity-50"
          >
            {url.replace("https://github.com/", "")}
          </button>
        ))}
      </div>

      <button
        type="submit"
        disabled={loading}
        className="mt-1 self-start rounded-full bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground transition hover:bg-primary/90 disabled:opacity-50"
      >
        {loading ? "scanning…" : "Scan repository"}
      </button>

      {loading && (
        <p className="text-xs text-muted-foreground">
          Cloning, installing with <span className="font-mono">--ignore-scripts</span>,
          parsing, and querying OSV. A first scan of a real repo takes a minute or two.
        </p>
      )}
      {error && <p className="text-sm text-destructive">{error}</p>}
    </form>
  );
}
