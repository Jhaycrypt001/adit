import {
  type CSSProperties,
  forwardRef,
  useMemo,
  useRef,
} from "react";
import {
  motion,
  motionValue,
  useAnimationFrame,
  useTransform,
  type MotionValue,
} from "motion/react";
import { useMousePositionRef } from "@/hooks/use-mouse-position-ref";

/**
 * Text whose letters respond individually to how close the cursor is.
 *
 * Structured so every hook sits at the top level of a component: the letters
 * are a real child component, and their `MotionValue`s are built with the
 * `motionValue()` factory rather than `useMotionValue` in a loop. The obvious
 * shape -- mapping over the letters and calling hooks inside the map -- happens
 * to work only while the label's length never changes, and breaks silently
 * (wrong letter reading the wrong value) the first time it does.
 *
 * Nothing here re-renders on mouse move. The pointer lands in a ref, the
 * per-frame loop writes into MotionValues, and Motion drives the DOM directly.
 */

// A style map whose every property accepts a number or a string, since these
// are interpolation endpoints rather than final CSS values.
type CSSPropertiesWithValues = {
  [K in keyof CSSProperties]: string | number;
};

interface StyleValue<T extends keyof CSSPropertiesWithValues> {
  from: CSSPropertiesWithValues[T];
  to: CSSPropertiesWithValues[T];
}

export type ProximityStyles = Partial<{
  [K in keyof CSSPropertiesWithValues]: StyleValue<K>;
}>;

interface TextProps extends React.HTMLAttributes<HTMLSpanElement> {
  label: string;
  styles: ProximityStyles;
  containerRef: React.RefObject<HTMLDivElement | null>;
  radius?: number;
  falloff?: "linear" | "exponential" | "gaussian";
}

interface LetterProps {
  char: string;
  proximity: MotionValue<number>;
  styles: ProximityStyles;
  registerRef: (el: HTMLSpanElement | null) => void;
}

function ProximityLetter({ char, proximity, styles, registerRef }: LetterProps) {
  // `styles` is a literal at the call site, so its key set is fixed for the
  // life of this component -- which is what makes the hook count stable.
  // Widened to the union rather than kept per-key: these are interpolation
  // endpoints handed straight to Motion, and the per-property CSS types add
  // nothing once they are inside a MotionValue.
  const entries = Object.entries(styles) as [
    string,
    { from: string | number; to: string | number },
  ][];

  const transformed: Record<string, MotionValue<string | number>> = {};
  for (const [key, value] of entries) {
    // eslint-disable-next-line react-hooks/rules-of-hooks -- fixed-length key set, see above
    transformed[key] = useTransform(proximity, [0, 1], [value.from, value.to]);
  }

  return (
    <motion.span
      ref={registerRef}
      className="inline-block"
      aria-hidden="true"
      style={transformed}
    >
      {char}
    </motion.span>
  );
}

const TextCursorProximity = forwardRef<HTMLSpanElement, TextProps>(
  (
    {
      label,
      styles,
      containerRef,
      radius = 50,
      falloff = "linear",
      className,
      onClick,
      ...props
    },
    ref,
  ) => {
    const letterRefs = useRef<(HTMLSpanElement | null)[]>([]);
    const mousePositionRef = useMousePositionRef(containerRef);

    const letterCount = label.replace(/\s/g, "").length;
    // Rebuilt only when the label's length changes, so a dynamic label stays
    // correct instead of reusing a stale, differently-sized array.
    const proximities = useMemo(
      () => Array.from({ length: letterCount }, () => motionValue(0)),
      [letterCount],
    );

    const calculateFalloff = (distance: number): number => {
      const normalized = Math.min(Math.max(1 - distance / radius, 0), 1);
      switch (falloff) {
        case "exponential":
          return normalized * normalized;
        case "gaussian":
          return Math.exp(-Math.pow(distance / (radius / 2), 2) / 2);
        default:
          return normalized;
      }
    };

    useAnimationFrame(() => {
      const container = containerRef.current;
      if (!container) return;
      const containerRect = container.getBoundingClientRect();
      const { x: mx, y: my } = mousePositionRef.current;

      for (let i = 0; i < letterRefs.current.length; i++) {
        const letterEl = letterRefs.current[i];
        const proximity = proximities[i];
        if (!letterEl || !proximity) continue;

        const rect = letterEl.getBoundingClientRect();
        const cx = rect.left + rect.width / 2 - containerRect.left;
        const cy = rect.top + rect.height / 2 - containerRect.top;
        const distance = Math.hypot(mx - cx, my - cy);

        proximity.set(calculateFalloff(distance));
      }
    });

    const words = label.split(" ");
    let letterIndex = 0;

    return (
      <span
        ref={ref}
        className={`${className ?? ""} inline`}
        onClick={onClick}
        {...props}
      >
        {words.map((word, wordIndex) => (
          <span key={wordIndex} className="inline-block whitespace-nowrap">
            {word.split("").map((letter) => {
              const i = letterIndex++;
              return (
                <ProximityLetter
                  key={i}
                  char={letter}
                  proximity={proximities[i]}
                  styles={styles}
                  registerRef={(el) => {
                    letterRefs.current[i] = el;
                  }}
                />
              );
            })}
            {wordIndex < words.length - 1 && (
              <span className="inline-block">&nbsp;</span>
            )}
          </span>
        ))}
        {/* The visible letters are split and aria-hidden, so this is the only
            copy a screen reader ever announces. */}
        <span className="sr-only">{label}</span>
      </span>
    );
  },
);

TextCursorProximity.displayName = "TextCursorProximity";
export default TextCursorProximity;
