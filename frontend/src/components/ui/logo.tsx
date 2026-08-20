import { cn } from "@/lib/utils";

/**
 * The Adit keystone.
 *
 * Inline rather than an `<img>`, and filled with `currentColor`, so it takes
 * the colour of whatever it sits in. The source file ships a fixed dark olive,
 * which is invisible against this site's background. A logo that has to be
 * recoloured per placement is one that should not carry its own fill.
 */
export function Logo({ className }: { className?: string }) {
  return (
    <svg
      viewBox="8.178508 8.531762 47.664148 47.026875"
      role="img"
      aria-label="Adit"
      shapeRendering="geometricPrecision"
      className={cn("h-8 w-8", className)}
      fill="currentColor"
    >
      <path
        d="M 55.842656 8.531762 L 55.842656 13.8983 L 42.883775 13.8983 A 22 22 0 0 1 55.138768 39.372971 A 22.297379 22.297379 0 0 1 33.695352 55.558637 L 33.695352 36.919416 L 21.466285 36.919416 L 14.235559 55.463672 L 8.178508 55.463672 L 24.946707 13.8983 L 8.353918 13.8983 L 8.353918 8.531762 L 55.842656 8.531762 Z M 33.695352 13.8983 L 30.557535 13.8983 L 30.557535 32.995313 L 33.695352 32.995313 L 33.695352 13.8983 Z M 25.194004 32.995313 L 25.194004 27.286348 L 22.834977 32.995313 L 22.848046 32.995313 L 25.194004 32.995313 Z"
        fillRule="nonzero"
      />
      <path
        d="M 30.557535 39.530195 L 30.557535 55.463672 L 25.194004 55.463672 L 25.194004 39.530195 L 30.557535 39.530195 Z"
        fillRule="nonzero"
      />
    </svg>
  );
}

/** The keystone beside the wordmark, for headers. */
export function LogoLockup({
  className,
  markClassName,
}: {
  className?: string;
  markClassName?: string;
}) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <Logo className={cn("h-7 w-7", markClassName)} />
      <span className="text-lg font-semibold tracking-tight">Adit</span>
    </span>
  );
}
