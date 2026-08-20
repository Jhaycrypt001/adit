import type { ScanReport } from "@/lib/types";

/**
 * Tabs across the scans made in this session.
 *
 * Results used to render one after another, so a second scan pushed the first
 * down the page and a fifth made the console unusable. Each scan is now a tab
 * and only the selected one is drawn. Comparing two runs is a click, and the
 * dashboard stays the same height no matter how many you do.
 */
export function ScanHistory({
  reports,
  activeIndex,
  onSelect,
  onRemove,
}: {
  reports: ScanReport[];
  activeIndex: number;
  onSelect: (i: number) => void;
  onRemove: (i: number) => void;
}) {
  if (reports.length <= 1) return null;

  return (
    <div className="flex flex-col gap-2">
      <p className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">
        This session&rsquo;s scans
      </p>
      <div className="flex flex-wrap gap-2">
        {reports.map((r, i) => {
          const actionable = r.findings.filter((f) => f.actionable).length;
          const active = i === activeIndex;
          return (
            <span
              key={r.scan_id}
              className={`group flex items-center gap-2 rounded-full border py-1 pl-3 pr-1.5 text-xs transition ${
                active
                  ? "border-primary/60 bg-primary/10 text-foreground"
                  : "border-border text-muted-foreground hover:text-foreground"
              }`}
            >
              <button
                type="button"
                onClick={() => onSelect(i)}
                className="flex items-center gap-2"
                title={`${r.package} · ${r.headline}`}
              >
                <span
                  aria-hidden
                  className="h-1.5 w-1.5 shrink-0 rounded-full"
                  style={{
                    background:
                      actionable > 0 ? "var(--status-critical)" : "var(--status-good)",
                  }}
                />
                <span className="max-w-[16rem] truncate font-mono">{r.package}</span>
                <span className="tabular-nums opacity-70">{actionable}</span>
              </button>
              <button
                type="button"
                onClick={() => onRemove(i)}
                aria-label={`Remove ${r.package} from this list`}
                className="rounded-full px-1 text-muted-foreground opacity-0 transition hover:text-foreground group-hover:opacity-100"
              >
                ×
              </button>
            </span>
          );
        })}
      </div>
    </div>
  );
}
