import CarouselStacked, { type Slide } from "@/components/ui/carousel-07";
import {
  AbstentionVisual,
  BindingVisual,
  BlastRadiusVisual,
  ReachabilityVisual,
  TemporalVisual,
} from "@/components/ui/capability-visuals";

/**
 * The five questions the one kernel answers. They are the same traversal with a
 * different sort key, which is the actual reason a single engine covers all
 * three hackathon tracks without special-casing the query layer.
 *
 * Each card carries a diagram of its own query rather than a photograph. Stock
 * imagery of circuit boards said nothing about reachability and read as filler
 * to exactly the audience this page is written for.
 */
const SLIDES: Slide[] = [
  {
    visual: <ReachabilityVisual className="h-full w-full" />,
    title: "Reachability",
    description:
      "Does a call path exist from one of your entrypoints to the vulnerable function, four levels deep in the lockfile?",
    badge: "Runtime CVE",
  },
  {
    visual: <BlastRadiusVisual className="h-full w-full" />,
    title: "Blast radius",
    description:
      "A preinstall hook already ran. Reachability is meaningless here, so the question inverts: who resolved it, and how far does it reach?",
    badge: "Install-time",
  },
  {
    visual: <TemporalVisual className="h-full w-full" />,
    title: "Temporal validity",
    description:
      "Was the bad version live in the window your lockfile resolved it? Every edge carries valid_from and valid_to, so this is a range predicate.",
    badge: "Bitemporal",
  },
  {
    visual: <AbstentionVisual className="h-full w-full" />,
    title: "Abstention",
    description:
      "The traversal returns empty and Adit says so, with the frontier it actually explored. A vector index can only ever guess.",
    badge: "Not found",
  },
  {
    visual: <BindingVisual className="h-full w-full" />,
    title: "Cross-package binding",
    description:
      "Bind an import specifier to the package's own internal symbol. Lazy by design: only packages on a path to an advisory are ever parsed.",
    badge: "The hard part",
  },
];

export function Capabilities() {
  return (
    <section
      id="capabilities"
      className="relative w-full border-t border-border bg-background py-24 md:py-32"
    >
      <div className="mx-auto mb-4 max-w-6xl px-6 sm:px-10 lg:px-20">
        <p className="mb-4 text-xs font-medium uppercase tracking-[0.25em] text-muted-foreground">
          One kernel, five questions
        </p>
        <h2 className="max-w-2xl text-3xl font-light leading-tight tracking-tight sm:text-4xl lg:text-5xl">
          Every one of these is{" "}
          <span className="text-primary">the same traversal</span> with a
          different sort key.
        </h2>
        <p className="mt-5 max-w-xl text-[0.95rem] leading-relaxed text-muted-foreground">
          That is not a metaphor stretched to justify a three-in-one. It is why
          the query layer contains three Cypher shapes and nothing else.
        </p>
      </div>

      <CarouselStacked slides={SLIDES} className="bg-transparent py-6" />
    </section>
  );
}
