import { LayoutGroup, motion } from "motion/react";
import { TextRotate } from "@/components/ui/text-rotate";

/**
 * The argument the rest of the page assumes but never actually makes: why this
 * is a graph problem rather than an index problem.
 *
 * The rotating word is the list of things similarity genuinely cannot compute.
 * It rotates because the list is the point -- one example would read as a
 * cherry-pick, and five stacked as a bullet list would read as filler.
 */
const CANNOT_ANSWER = [
  "reachability",
  "temporal validity",
  "absence",
  "provenance",
  "blast radius",
];

const COMPARISON = [
  {
    label: "Vector search",
    verdict: "Cannot do this at all",
    detail:
      "Similarity is not reachability. Two functions that look alike have no call edge between them, and no amount of embedding distance invents one.",
  },
  {
    label: "Relational",
    verdict: "Possible, and miserable",
    detail:
      "Recursive CTEs across two heterogeneous graphs — the intra-repo call graph and the inter-package dependency graph — joined at the symbol boundary, over millions of edges.",
  },
  {
    label: "Graph-native",
    verdict: "One traversal",
    detail:
      "Topology indexes for the closure, algo.MSpaths to resolve every entrypoint against every advisory server-side, and object-storage economics that make keeping history affordable.",
  },
];

export function WhyAGraph() {
  return (
    <section
      id="why-a-graph"
      className="relative w-full border-t border-border bg-background px-6 py-24 sm:px-10 md:py-32 lg:px-20"
    >
      <div className="mx-auto max-w-6xl">
        <p className="mb-6 text-xs font-medium uppercase tracking-[0.25em] text-muted-foreground">
          Why a graph
        </p>

        {/* LayoutGroup lets the fixed half slide as the rotating half changes
            width, instead of the line jumping on every swap. */}
        <LayoutGroup>
          <motion.h2
            layout
            className="flex flex-wrap items-center gap-x-3 text-3xl font-light leading-tight tracking-tight sm:text-4xl lg:text-5xl"
          >
            <motion.span
              layout
              transition={{ type: "spring", damping: 30, stiffness: 400 }}
            >
              A vector index cannot answer
            </motion.span>
            <TextRotate
              texts={CANNOT_ANSWER}
              mainClassName="overflow-hidden justify-center rounded-lg bg-primary px-2 py-0.5 text-primary-foreground sm:px-2.5 md:px-3 md:py-1"
              staggerFrom="last"
              initial={{ y: "100%" }}
              animate={{ y: 0 }}
              exit={{ y: "-120%" }}
              staggerDuration={0.025}
              splitLevelClassName="overflow-hidden pb-0.5 md:pb-1"
              transition={{ type: "spring", damping: 30, stiffness: 400 }}
              rotationInterval={2200}
            />
          </motion.h2>
        </LayoutGroup>

        <p className="mt-7 max-w-2xl text-[0.95rem] leading-relaxed text-muted-foreground">
          Not because the model is too small. Because the question is structural:
          it asks whether a path exists between two nodes, and a nearest-neighbour
          lookup has no notion of a path. That is the whole reason this is built
          on a graph engine rather than an index with a graph-shaped API.
        </p>

        <dl className="mt-14 grid gap-px overflow-hidden rounded-xl border border-border bg-border sm:grid-cols-3">
          {COMPARISON.map((row) => (
            <div key={row.label} className="flex flex-col bg-background p-6">
              <dt className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                {row.label}
              </dt>
              <dd className="mt-3 flex flex-1 flex-col">
                <span className="text-lg font-medium tracking-tight">{row.verdict}</span>
                <span className="mt-2 text-sm leading-relaxed text-muted-foreground">
                  {row.detail}
                </span>
              </dd>
            </div>
          ))}
        </dl>
      </div>
    </section>
  );
}
