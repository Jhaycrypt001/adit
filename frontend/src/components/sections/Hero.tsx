import { BlackHoleHeroSection } from "@/components/ui/blackhole-hero-section";
import { LiquidMetalButton } from "@/components/ui/liquid-metal-button";
import { useNarrow } from "@/hooks/use-narrow";
import { Logo } from "@/components/ui/logo";

/**
 * The hero is built around the picture rather than laid on top of it.
 *
 * The hole is pushed off centre with `focus` so the busy half and the reading
 * half never overlap, and `scrim` darkens only the edge the copy sits on -- a
 * flat overlay could not do that without greying out the halo too.
 *
 * A phone has no room to stand the two side by side, so the whole arrangement
 * turns through 90 degrees: copy at the top under a veil, hole low and whole in
 * the bottom third. Half a hole reads as a mistake; the ray count drops with it
 * because a phone pays for every step.
 *
 * The subject is not decoration. An adit is the passage driven into a mountain
 * to reach what cannot be reached from above, and the one thing a black hole
 * does to light is bend the path it takes. The page is about paths.
 */
export function Hero({ onOpenConsole }: { onOpenConsole: () => void }) {
  const narrow = useNarrow();

  return (
    <section id="top" className="relative min-h-[92svh] w-full md:min-h-[760px]">
      <BlackHoleHeroSection
        focus={narrow ? [0.5, 0.78] : [0.72, 0.46]}
        scrim={narrow ? "top" : "left"}
        scrimStrength={0.9}
        distance={24}
        elevation={narrow ? -7 : -5.5}
        fov={narrow ? 58 : 42}
        glow={narrow ? 0.85 : 1}
        steps={narrow ? 200 : 300}
        resolution={narrow ? 0.6 : 0.7}
      >
        <div className="flex h-full min-h-[92svh] items-start px-6 pt-16 sm:px-10 md:min-h-[760px] md:items-center md:pt-0 lg:px-20">
          <div className="max-w-[36rem]">
            <div className="mb-7 flex items-center gap-3">
              <Logo className="h-9 w-9 text-primary" />
              <div className="flex flex-col leading-none">
                <span className="text-lg font-semibold tracking-tight text-white">Adit</span>
                <span className="mt-1 text-[10px] uppercase tracking-[0.2em] text-white/45">
                  Reachability engine
                </span>
              </div>
            </div>

            <h1 className="text-[2.5rem] font-light leading-[1.05] tracking-[-0.03em] text-white sm:text-6xl lg:text-[4.25rem]">
              Does your code
              <br />
              actually reach it?
            </h1>

            <p className="mt-6 max-w-md text-[0.95rem] leading-relaxed text-white/60 md:mt-7">
              Your lockfile has 47 advisories. Three of them are callable from
              your own entrypoints. Adit walks the call graph across the package
              boundary and shows you the path: file and line, all the way
              in. Not a score. A path.
            </p>

            <div className="mt-8 flex flex-wrap items-center gap-4 md:mt-10">
              <LiquidMetalButton label="Run a scan" width={150} onClick={onOpenConsole} />
              <a
                href="#how"
                className="rounded-full border border-white/20 px-6 py-3 text-sm text-white/80 transition hover:border-white/40 hover:text-white"
              >
                How it works
              </a>
            </div>

            {/* Every number here is checkable against the repository. The
                middle one used to read "172 tests" and had to change when the
                suite was removed: a headline figure that is no longer true is
                worse than no figure, and this is the first thing anyone reads.

                The third is held back until sm: at 390px three of these wrap
                onto a second line, which on this layout lands directly on the
                brightest part of the disc and stops being readable. */}
            <dl className="mt-10 flex flex-wrap gap-x-8 gap-y-4 md:mt-12">
              {[
                ["47.6×", "MSpaths vs fan-out", false],
                ["3", "Cypher shapes, total", false],
                ["0", "LLM calls on the hot path", true],
              ].map(([value, label, wideOnly]) => (
                <div key={label as string} className={wideOnly ? "hidden sm:block" : undefined}>
                  <dt className="text-xl font-semibold text-white sm:text-2xl">{value}</dt>
                  <dd className="mt-0.5 text-[11px] uppercase tracking-[0.15em] text-white/40">
                    {label}
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        </div>
      </BlackHoleHeroSection>
    </section>
  );
}
