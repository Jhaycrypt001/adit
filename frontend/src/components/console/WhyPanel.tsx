import { useState } from "react";
import { ApiError, whyReachable } from "@/lib/api";
import type { WhyResult } from "@/lib/types";
import type { ReportSummary, SymbolOption } from "@/lib/report";
import { CopyButton } from "./CopyButton";

interface Props {
  scanId: string | null;
  summary: ReportSummary | null;
  initialSource?: string;
  initialTarget?: string;
}

function SymbolField({
  id,
  label,
  hint,
  value,
  onChange,
  options,
  disabled,
}: {
  id: string;
  label: string;
  hint: string;
  value: string;
  onChange: (v: string) => void;
  options: SymbolOption[];
  disabled: boolean;
}) {
  return (
    <div className="flex flex-col gap-2">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <p className="text-[11px] leading-relaxed text-muted-foreground">{hint}</p>
      {options.length > 0 ? (
        <select
          id={id}
          value={options.some((o) => o.key === value) ? value : ""}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
          className="rounded-lg border border-input bg-background px-3 py-2.5 font-mono text-sm outline-none transition focus:border-primary/60 focus:ring-1 focus:ring-primary/40 disabled:opacity-50"
        >
          <option value="">— choose a symbol from this scan —</option>
          {options.map((o) => (
            <option key={o.key} value={o.key}>
              {o.isTarget ? "◆ " : ""}
              {o.label} — {o.key}
            </option>
          ))}
        </select>
      ) : null}
      <input
        id={options.length > 0 ? `${id}-raw` : id}
        required
        disabled={disabled}
        placeholder="sym:pkg@version:module#name"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-lg border border-input bg-background px-3 py-2.5 font-mono text-xs outline-none transition focus:border-primary/60 focus:ring-1 focus:ring-primary/40 disabled:opacity-50"
      />
    </div>
  );
}

/**
 * Explain reachability between two exact symbol keys.
 *
 * The endpoint refuses to resolve bare names — silently matching the wrong
 * symbol over a public HTTP surface is a worse failure than making the caller
 * be precise. That is defensible for the API and hostile as a UI, so the keys
 * are offered from the scan that produced them rather than typed from memory.
 * The free-text field stays for keys from elsewhere.
 */
export function WhyPanel({ scanId, summary, initialSource = "", initialTarget = "" }: Props) {
  const [source, setSource] = useState(initialSource);
  const [target, setTarget] = useState(initialTarget);
  const [maxLen, setMaxLen] = useState(12);
  const [result, setResult] = useState<WhyResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const options = summary?.symbols ?? [];
  const entrypoints = options.filter((o) => !o.isTarget);
  const targets = options.filter((o) => o.isTarget);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      setResult(
        await whyReachable(source.trim(), target.trim(), {
          maxLen,
          scanId: scanId ?? undefined,
        }),
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "lookup failed");
    } finally {
      setLoading(false);
    }
  }

  function swap() {
    setSource(target);
    setTarget(source);
  }

  return (
    <div className="flex flex-col gap-6">
      <p className="max-w-prose text-sm leading-relaxed text-muted-foreground">
        Ask whether one symbol can reach another, and see the shortest path if it can.
        Keys come from a scan&rsquo;s results &mdash;{" "}
        <span className="font-mono text-xs text-foreground">◆</span> marks a symbol that
        appeared as a vulnerable target.
      </p>

      {options.length === 0 && (
        <p className="rounded-lg border border-border bg-muted/20 p-4 text-sm leading-relaxed text-muted-foreground">
          No scan in this session, so there are no symbol keys to choose from. Run a
          scan that finds at least one path, or paste keys directly below.
        </p>
      )}

      <form onSubmit={submit} className="flex flex-col gap-5">
        <SymbolField
          id="why-source"
          label="Source symbol"
          hint="Usually an entrypoint — an exported function or a route handler."
          value={source}
          onChange={setSource}
          options={entrypoints.length > 0 ? entrypoints : options}
          disabled={loading}
        />

        <button
          type="button"
          onClick={swap}
          disabled={loading}
          className="self-start rounded-full border border-border px-3 py-1 text-[11px] text-muted-foreground transition hover:border-primary/50 hover:text-foreground disabled:opacity-50"
        >
          ↕ Swap
        </button>

        <SymbolField
          id="why-target"
          label="Target symbol"
          hint="Usually the vulnerable function inside a dependency."
          value={target}
          onChange={setTarget}
          options={targets.length > 0 ? targets : options}
          disabled={loading}
        />

        <div className="flex flex-wrap items-end gap-4">
          <label className="flex flex-col gap-1.5 text-xs text-muted-foreground">
            Max hops
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
            disabled={loading || !source.trim() || !target.trim()}
            className="rounded-full bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground transition hover:bg-primary/90 disabled:opacity-50"
          >
            {loading ? "Traversing…" : "Why reachable"}
          </button>
        </div>

        {scanId && (
          <p className="font-mono text-[11px] text-muted-foreground">
            scoped to scan_id {scanId.slice(0, 12)}…
          </p>
        )}
        {error && <p className="text-sm text-destructive">{error}</p>}
      </form>

      {result && (
        <div className="rounded-xl border border-border bg-card/40 p-5">
          {result.reachable ? (
            <>
              <div className="flex flex-wrap items-center gap-3">
                <span className="rounded-full bg-destructive/15 px-2.5 py-0.5 text-xs font-semibold text-destructive ring-1 ring-destructive/30">
                  reachable
                </span>
                <span className="text-sm text-muted-foreground">
                  shortest path is {result.depth} hop{result.depth === 1 ? "" : "s"}
                </span>
              </div>
              <ol className="mt-4 flex flex-col gap-0">
                {result.path?.map((n, i) => {
                  const last = i === (result.path?.length ?? 0) - 1;
                  return (
                    <li key={i} className="flex gap-3">
                      <div className="flex flex-col items-center">
                        <span
                          className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${last ? "bg-destructive" : "bg-primary"}`}
                        />
                        {!last && <span className="w-px flex-1 bg-border" />}
                      </div>
                      <div className={`min-w-0 flex-1 ${last ? "pb-0" : "pb-4"}`}>
                        <p className="font-mono text-sm text-foreground">
                          {n.name ?? "?"}
                          {last && (
                            <span className="ml-2 text-xs text-destructive">← vulnerable</span>
                          )}
                        </p>
                        {n.file && (
                          <p className="font-mono text-[11px] text-muted-foreground">
                            {n.file}
                            {n.line != null ? `:${n.line}` : ""}
                          </p>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ol>
              <div className="mt-4">
                <CopyButton
                  value={(result.path ?? [])
                    .map(
                      (n) =>
                        `${n.name ?? "?"}${n.file ? ` (${n.file}${n.line != null ? `:${n.line}` : ""})` : ""}`,
                    )
                    .join(" -> ")}
                  label="Copy path"
                />
              </div>
            </>
          ) : (
            <>
              <span className="rounded-full bg-emerald-500/10 px-2.5 py-0.5 text-xs font-semibold text-emerald-400 ring-1 ring-emerald-500/25">
                not reachable
              </span>
              <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
                {result.explanation}
              </p>
              <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
                The traversal completed and found nothing. That is a fact about the
                graph, not a failure to answer.
              </p>
            </>
          )}
        </div>
      )}
    </div>
  );
}
