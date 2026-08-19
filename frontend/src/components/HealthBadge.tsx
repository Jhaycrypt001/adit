import { useEffect, useState } from "react";
import { getHealth } from "../lib/api";

type State = "checking" | "ok" | "down";

/**
 * Asked before the console offers a scan. A connection failure surfacing inside
 * a POST is a worse first impression than a clear "database not running" shown
 * up front -- which is the same reason `/health` exists on the API at all.
 */
export function HealthBadge() {
  const [state, setState] = useState<State>("checking");

  useEffect(() => {
    let cancelled = false;
    getHealth()
      .then(() => !cancelled && setState("ok"))
      .catch(() => !cancelled && setState("down"));
    return () => {
      cancelled = true;
    };
  }, []);

  const dot = {
    checking: "bg-amber-400",
    ok: "bg-emerald-400",
    down: "bg-destructive",
  }[state];

  const label = {
    checking: "checking API…",
    ok: "API online",
    down: "API unreachable",
  }[state];

  return (
    <span className="flex items-center gap-2 text-xs text-muted-foreground">
      <span className={`h-2 w-2 rounded-full ${dot}`} />
      {label}
    </span>
  );
}
