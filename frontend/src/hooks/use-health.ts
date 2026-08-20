import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE_URL, getHealth } from "@/lib/api";

export type HealthState = "checking" | "online" | "offline";

export interface Health {
  state: HealthState;
  detail: string | null;
  baseUrl: string;
  lastChecked: Date | null;
  /** Force an immediate re-check, e.g. from a "retry" button. */
  refresh: () => void;
}

/**
 * Liveness of the API, polled.
 *
 * The old badge checked once on mount and then believed itself forever, so
 * starting the backend after opening the page left the console insisting the
 * API was unreachable until a manual reload -- which reads as the product
 * being broken when it is simply out of date. This re-checks on an interval,
 * backs off while it is down so a dead backend is not hammered, and re-checks
 * immediately when the tab is focused again, which is when a user who just ran
 * `docker compose up` comes back.
 */
export function useHealth(intervalMs = 15000): Health {
  const [state, setState] = useState<HealthState>("checking");
  const [detail, setDetail] = useState<string | null>(null);
  const [lastChecked, setLastChecked] = useState<Date | null>(null);
  const timer = useRef<number | null>(null);
  const failures = useRef(0);
  const alive = useRef(true);

  const check = useCallback(async () => {
    try {
      await getHealth();
      if (!alive.current) return;
      failures.current = 0;
      setState("online");
      setDetail(null);
    } catch (err) {
      if (!alive.current) return;
      failures.current += 1;
      setState("offline");
      setDetail(err instanceof Error ? err.message : "unreachable");
    } finally {
      if (alive.current) setLastChecked(new Date());
    }
  }, []);

  useEffect(() => {
    alive.current = true;

    const schedule = () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
      // Back off up to 8x while it stays down; snap back the moment it works.
      const factor = Math.min(2 ** Math.max(0, failures.current - 1), 8);
      const delay = failures.current === 0 ? intervalMs : intervalMs * factor;
      timer.current = window.setTimeout(async () => {
        await check();
        schedule();
      }, delay);
    };

    void check().then(schedule);

    const onFocus = () => void check();
    window.addEventListener("focus", onFocus);

    return () => {
      alive.current = false;
      if (timer.current !== null) window.clearTimeout(timer.current);
      window.removeEventListener("focus", onFocus);
    };
  }, [check, intervalMs]);

  const refresh = useCallback(() => {
    failures.current = 0;
    setState("checking");
    void check();
  }, [check]);

  return { state, detail, baseUrl: API_BASE_URL, lastChecked, refresh };
}
