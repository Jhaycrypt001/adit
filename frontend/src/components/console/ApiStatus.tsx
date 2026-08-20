import type { Health } from "@/hooks/use-health";

const DOT: Record<Health["state"], string> = {
  checking: "bg-amber-400 animate-pulse",
  online: "bg-emerald-400",
  offline: "bg-destructive",
};

const LABEL: Record<Health["state"], string> = {
  checking: "checking API",
  online: "API online",
  offline: "API unreachable",
};

export function ApiStatusBadge({ health }: { health: Health }) {
  return (
    <button
      type="button"
      onClick={health.refresh}
      title={`${health.baseUrl}${health.lastChecked ? ` · checked ${health.lastChecked.toLocaleTimeString()}` : ""}`}
      className="flex items-center gap-2 rounded-full border border-border px-3 py-1.5 text-xs text-muted-foreground transition hover:border-primary/50 hover:text-foreground"
    >
      <span className={`h-2 w-2 rounded-full ${DOT[health.state]}`} />
      {LABEL[health.state]}
    </button>
  );
}

/**
 * Shown in place of the tools when the API is down.
 *
 * The console previously rendered a full set of inputs that could not possibly
 * work, and a four-word badge explaining why. Every control being live while
 * nothing behind them responds is worse than an empty state -- this says what
 * is wrong, where it looked, and the exact command that fixes it.
 */
export function ApiOfflineNotice({ health }: { health: Health }) {
  return (
    <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-5">
      <div className="flex items-start gap-3">
        <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-destructive" />
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold">The Adit API is not responding</h3>
          <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
            Tried{" "}
            <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs text-foreground">
              {health.baseUrl}
            </code>
            . The backend and HydraDB run as containers &mdash; start them from the
            repository root:
          </p>

          <pre className="mt-3 overflow-x-auto rounded-lg border border-border bg-background p-3">
            <code className="font-mono text-xs text-foreground">
              docker compose up -d
            </code>
          </pre>

          <details className="mt-3">
            <summary className="cursor-pointer text-xs text-muted-foreground hover:text-foreground">
              Already running?
            </summary>
            <ul className="mt-2 flex list-disc flex-col gap-1.5 pl-4 text-xs leading-relaxed text-muted-foreground">
              <li>
                Check both containers are healthy:{" "}
                <code className="font-mono text-foreground">docker compose ps</code>
              </li>
              <li>
                If writes are failing, HydraDB&rsquo;s local storage backend can wedge.
                Reset it:{" "}
                <code className="font-mono text-foreground">
                  docker compose down -v &amp;&amp; docker compose up -d
                </code>
              </li>
              <li>
                Pointing somewhere else? Set{" "}
                <code className="font-mono text-foreground">VITE_API_URL</code> in{" "}
                <code className="font-mono text-foreground">frontend/.env</code> and
                restart the dev server.
              </li>
            </ul>
            {health.detail && (
              <p className="mt-2 font-mono text-[11px] leading-relaxed text-muted-foreground/80">
                {health.detail}
              </p>
            )}
          </details>

          <button
            type="button"
            onClick={health.refresh}
            className="mt-4 rounded-full border border-border px-4 py-1.5 text-xs font-medium transition hover:border-primary/50 hover:text-foreground"
          >
            {health.state === "checking" ? "Checking…" : "Retry now"}
          </button>
          <p className="mt-2 text-[11px] text-muted-foreground">
            Re-checking automatically
            {health.lastChecked
              ? ` · last tried ${health.lastChecked.toLocaleTimeString()}`
              : ""}
          </p>
        </div>
      </div>
    </div>
  );
}
