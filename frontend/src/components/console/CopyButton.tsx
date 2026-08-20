import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Copy-to-clipboard with honest failure.
 *
 * `navigator.clipboard` is unavailable on insecure origins and can be denied by
 * permission, so a button that always claims success is lying some of the time.
 * This reports what actually happened.
 */
export function CopyButton({
  value,
  label = "Copy",
  className = "",
  title,
}: {
  value: string;
  label?: string;
  className?: string;
  title?: string;
}) {
  const [state, setState] = useState<"idle" | "ok" | "fail">("idle");
  const timer = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    },
    [],
  );

  const copy = useCallback(async () => {
    try {
      if (!navigator.clipboard) throw new Error("clipboard unavailable");
      await navigator.clipboard.writeText(value);
      setState("ok");
    } catch {
      setState("fail");
    }
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setState("idle"), 1600);
  }, [value]);

  return (
    <button
      type="button"
      onClick={copy}
      title={title ?? value}
      className={`rounded border border-border px-2 py-0.5 font-mono text-[10px] text-muted-foreground transition hover:border-primary/50 hover:text-foreground ${className}`}
    >
      {state === "ok" ? "copied" : state === "fail" ? "copy failed" : label}
    </button>
  );
}
