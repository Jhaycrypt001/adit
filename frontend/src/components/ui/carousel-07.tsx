import * as React from "react";
import {
  motion,
  useMotionValue,
  useTransform,
  animate,
  type PanInfo,
  type MotionValue,
} from "motion/react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";

export interface Slide {
  /** A diagram of the query this card describes. Deliberately not a photograph
   *  -- see capability-visuals.tsx for why stock imagery was dropped. */
  visual: React.ReactNode;
  title: string;
  description: string;
  badge: string;
}

interface CarouselConfig {
  distanceDivisor: number;
  velocityDivisor: number;
  sensitivity: number;
  xMultiplier: number;
  yMultiplier: number;
  rotationMultiplier: number;
  scaleReduction: number;
}

/**
 * Drag physics scaled to the viewport. A phone's thumb travels a fraction of
 * the distance a trackpad drag does, so the same divisors would make the deck
 * feel glued down on mobile and twitchy on a desktop.
 */
const getCarouselConfig = (width: number): CarouselConfig => {
  if (width < 640) {
    return {
      distanceDivisor: 120,
      velocityDivisor: 500,
      sensitivity: 180,
      xMultiplier: 90,
      yMultiplier: 20,
      rotationMultiplier: 8,
      scaleReduction: 0.06,
    };
  }
  if (width < 1024) {
    return {
      distanceDivisor: 160,
      velocityDivisor: 650,
      sensitivity: 220,
      xMultiplier: 130,
      yMultiplier: 30,
      rotationMultiplier: 10,
      scaleReduction: 0.09,
    };
  }
  return {
    distanceDivisor: 200,
    velocityDivisor: 800,
    sensitivity: 250,
    xMultiplier: 170,
    yMultiplier: 40,
    rotationMultiplier: 12,
    scaleReduction: 0.12,
  };
};

export interface CarouselStackedProps {
  slides: Slide[];
  className?: string;
}

const CarouselStacked = ({ slides, className }: CarouselStackedProps) => {
  const scrollProgress = useMotionValue(0);
  const startProgress = React.useRef(0);
  // Read once during initialisation rather than set from an effect on mount.
  // Seeding this at 0 and correcting it afterwards meant the very first paint
  // laid the deck out with the phone config on every device, then re-rendered
  // -- a visible reflow for one frame, and a wasted render every time.
  // This app is client-rendered only, so `window` is always there.
  const [windowWidth, setWindowWidth] = React.useState(() => window.innerWidth);

  const total = slides.length;

  React.useEffect(() => {
    const handleResize = () => setWindowWidth(window.innerWidth);
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  const config = React.useMemo(
    () => getCarouselConfig(windowWidth),
    [windowWidth],
  );

  const handleDragStart = () => {
    startProgress.current = scrollProgress.get();
  };

  const handleDragEnd = (
    _: MouseEvent | TouchEvent | PointerEvent,
    info: PanInfo,
  ) => {
    const dragDistance = info.offset.x;
    const velocity = info.velocity.x;

    const distanceShift = -dragDistance / config.distanceDivisor;
    const velocityShift = -velocity / config.velocityDivisor;

    // Capped at three cards per flick. Without the clamp a fast swipe on a
    // trackpad can spin the deck most of the way round, which reads as a bug
    // rather than momentum.
    let totalShift = Math.round(distanceShift + velocityShift);
    totalShift = Math.max(-3, Math.min(3, totalShift));

    const target = Math.round(startProgress.current) + totalShift;

    animate(scrollProgress, target, {
      type: "spring",
      stiffness: 200,
      damping: 30,
      mass: 1,
    });
  };

  const step = (delta: number) => {
    animate(scrollProgress, Math.round(scrollProgress.get()) + delta, {
      type: "spring",
      stiffness: 200,
      damping: 30,
      mass: 1,
    });
  };

  return (
    <div
      className={cn(
        "flex w-full flex-col items-center justify-center overflow-hidden select-none",
        className,
      )}
    >
      <div className="relative flex h-80 w-full max-w-7xl items-center justify-center sm:h-[28rem] lg:h-[32rem]">
        {/* Transparent drag surface, above the cards so a drag anywhere in the
            deck moves it -- the cards themselves stay pointer-events-none. */}
        <motion.div
          drag="x"
          dragConstraints={{ left: 0, right: 0 }}
          onDragStart={handleDragStart}
          onDrag={(_, info) => {
            const delta = -info.delta.x / config.sensitivity;
            scrollProgress.set(scrollProgress.get() + delta);
          }}
          onDragEnd={handleDragEnd}
          className="absolute inset-0 z-50 cursor-grab active:cursor-grabbing"
        />

        {slides.map((slide, i) => (
          <Card
            key={slide.title}
            slide={slide}
            index={i}
            total={total}
            progress={scrollProgress}
            config={config}
          />
        ))}
      </div>

      {/* A drag surface is invisible to anyone not using a pointer. These are
          the same motion, reachable by keyboard and screen reader. */}
      <div className="mt-6 flex items-center gap-3">
        <button
          type="button"
          onClick={() => step(-1)}
          aria-label="Previous capability"
          className="flex h-10 w-10 items-center justify-center rounded-full border border-border text-muted-foreground transition hover:border-primary/50 hover:text-foreground"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M15 18l-6-6 6-6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
        <span className="text-xs uppercase tracking-[0.25em] text-muted-foreground">
          Drag
        </span>
        <button
          type="button"
          onClick={() => step(1)}
          aria-label="Next capability"
          className="flex h-10 w-10 items-center justify-center rounded-full border border-border text-muted-foreground transition hover:border-primary/50 hover:text-foreground"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M9 18l6-6-6-6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </div>
    </div>
  );
};

interface CardProps {
  slide: Slide;
  index: number;
  total: number;
  progress: MotionValue<number>;
  config: CarouselConfig;
}

const Card = ({ slide, index, total, progress, config }: CardProps) => {
  // Signed distance from the front of the deck, wrapped so the deck is a ring:
  // card 0 sits next to card n-1 rather than the whole stack flying back.
  const offset = useTransform(progress, (p) => {
    let diff = (index - p) % total;
    if (diff > total / 2) diff -= total;
    if (diff < -total / 2) diff += total;
    return diff;
  });

  const x = useTransform(offset, (o) => o * config.xMultiplier);
  const rotate = useTransform(offset, (o) =>
    // A dead zone at the front, or the top card jitters by a fraction of a
    // degree as the spring settles.
    Math.abs(o) < 0.05 ? 0 : o * config.rotationMultiplier,
  );
  const y = useTransform(offset, (o) =>
    Math.abs(o) < 0.05 ? 0 : Math.abs(o) * config.yMultiplier,
  );
  const scale = useTransform(
    offset,
    (o) => 1 - Math.abs(o) * config.scaleReduction,
  );
  const opacity = useTransform(
    offset,
    [-total / 2, -total / 2 + 0.5, 0, total / 2 - 0.5, total / 2],
    [0, 1, 1, 1, 0],
  );
  const zIndex = useTransform(offset, (o) => Math.round(100 - Math.abs(o) * 10));

  const shade = useTransform(offset, [-2, -0.5, 0, 0.5, 2], [0.5, 0.2, 0, 0.2, 0.5]);
  const textOpacity = useTransform(offset, [-0.5, 0, 0.5], [0, 1, 0]);

  return (
    <motion.div
      style={{ x, rotate, y, scale, opacity, zIndex }}
      className={cn(
        "group pointer-events-none absolute overflow-hidden rounded-2xl",
        "border border-border bg-[oklch(0.145_0.006_60)]",
        "h-56 w-44 sm:h-80 sm:w-56 lg:h-96 lg:w-64",
      )}
    >
      {/* A faint grid so the diagram reads as a plotted figure rather than
          floating in a void, masked out before it reaches the caption. */}
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.35]"
        style={{
          backgroundSize: "22px 22px",
          backgroundImage:
            "linear-gradient(to right, oklch(0.24 0.008 60) 1px, transparent 1px), linear-gradient(to bottom, oklch(0.24 0.008 60) 1px, transparent 1px)",
          maskImage: "linear-gradient(to bottom, black 0%, black 45%, transparent 72%)",
          WebkitMaskImage: "linear-gradient(to bottom, black 0%, black 45%, transparent 72%)",
        }}
      />

      <div className="pointer-events-none absolute inset-x-0 top-0 flex h-[58%] items-center justify-center px-3">
        <div className="h-full w-full transition-transform duration-700 group-hover:scale-105">
          {slide.visual}
        </div>
      </div>

      <motion.div
        style={{ opacity: shade }}
        className="pointer-events-none absolute inset-0 bg-black"
      />

      <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-transparent to-transparent" />

      <Badge className="absolute left-3 top-3 rounded-full border border-border bg-background/80 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground backdrop-blur-md sm:left-5 sm:top-5 sm:px-2.5 lg:left-6 lg:top-6">
        {slide.badge}
      </Badge>

      <div className="absolute bottom-5 left-3 right-3 text-center text-white sm:bottom-8 sm:left-5 sm:right-5 sm:text-left lg:bottom-10 lg:left-6 lg:right-6">
        <motion.p
          style={{ opacity: textOpacity }}
          className="mb-0.5 text-sm font-bold leading-tight drop-shadow-md sm:mb-1 sm:text-lg lg:text-xl"
        >
          {slide.title}
        </motion.p>
        <motion.p
          style={{ opacity: textOpacity }}
          className="hidden text-xs font-medium leading-snug text-white/70 sm:line-clamp-3 sm:block"
        >
          {slide.description}
        </motion.p>
      </div>
    </motion.div>
  );
};

export default CarouselStacked;
