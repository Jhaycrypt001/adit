import { type RefObject, useEffect, useRef } from "react";

/**
 * Tracks the pointer in coordinates relative to `containerRef`, in a ref rather
 * than state -- deliberately. A cursor-proximity effect samples this every
 * animation frame; putting it in state would re-render the whole subtree on
 * every mouse move, which is exactly the cost the ref exists to avoid.
 */
export const useMousePositionRef = (
  containerRef?: RefObject<HTMLElement | SVGElement | null>,
) => {
  const positionRef = useRef({ x: 0, y: 0 });

  useEffect(() => {
    const updatePosition = (x: number, y: number) => {
      if (containerRef && containerRef.current) {
        const rect = containerRef.current.getBoundingClientRect();
        // Kept relative even when the pointer leaves the container, so letters
        // near an edge fall off smoothly instead of snapping when it exits.
        positionRef.current = { x: x - rect.left, y: y - rect.top };
      } else {
        positionRef.current = { x, y };
      }
    };

    const handleMouseMove = (ev: MouseEvent) => {
      updatePosition(ev.clientX, ev.clientY);
    };

    const handleTouchMove = (ev: TouchEvent) => {
      const touch = ev.touches[0];
      if (touch) updatePosition(touch.clientX, touch.clientY);
    };

    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("touchmove", handleTouchMove);

    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("touchmove", handleTouchMove);
    };
  }, [containerRef]);

  return positionRef;
};
