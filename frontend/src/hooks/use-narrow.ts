import { useEffect, useState } from "react";

/**
 * True while the viewport matches `query`. Drives the layout swaps that CSS
 * alone cannot make -- the hero's WebGL scene takes its framing, field of view
 * and ray budget as props, not classes, so the breakpoint has to reach JS.
 */
export function useNarrow(query = "(max-width: 767px)") {
  const [narrow, setNarrow] = useState(false);

  useEffect(() => {
    const m = window.matchMedia(query);
    const sync = () => setNarrow(m.matches);
    sync();
    m.addEventListener("change", sync);
    return () => m.removeEventListener("change", sync);
  }, [query]);

  return narrow;
}
