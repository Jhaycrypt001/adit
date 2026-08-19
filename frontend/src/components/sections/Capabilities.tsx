import CarouselStacked, { type Slide } from "@/components/ui/carousel-07";

/**
 * The five questions the one kernel answers. They are the same traversal with a
 * different sort key, which is the actual reason a single engine covers all
 * three hackathon tracks without special-casing the query layer.
 */
const SLIDES: Slide[] = [
  {
    image:
      "https://images.unsplash.com/photo-1518770660439-4636190af475?auto=format&fit=crop&w=800&q=80",
    title: "Reachability",
    description:
      "Does a call path exist from one of your entrypoints to the vulnerable function, four levels deep in the lockfile?",
    badge: "Runtime CVE",
  },
  {
    image:
      "https://images.unsplash.com/photo-1550751827-4bd374c3f58b?auto=format&fit=crop&w=800&q=80",
    title: "Blast radius",
    description:
      "A preinstall hook already ran. Reachability is meaningless here, so the question inverts: who resolved it, and how far does it reach?",
    badge: "Install-time",
  },
  {
    image:
      "https://images.unsplash.com/photo-1451187580459-43490279c0fa?auto=format&fit=crop&w=800&q=80",
    title: "Temporal validity",
    description:
      "Was the bad version live in the window your lockfile resolved it? Every edge carries valid_from and valid_to, so this is a range predicate.",
    badge: "Bitemporal",
  },
  {
    image:
      "https://images.unsplash.com/photo-1526374965328-7f61d4dc18c5?auto=format&fit=crop&w=800&q=80",
    title: "Abstention",
    description:
      "The traversal returns empty and Adit says so, with the frontier it actually explored. A vector index can only ever guess.",
    badge: "Not found",
  },
  {
    image:
      "https://images.unsplash.com/photo-1558494949-ef010cbdcc31?auto=format&fit=crop&w=800&q=80",
    title: "Cross-package binding",
    description:
      "Bind `import { merge } from 'lodash'` to lodash's own internal symbol. Lazy by design: only packages on a path to an advisory are ever parsed.",
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
