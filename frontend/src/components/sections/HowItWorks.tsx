import { SiriWave } from "@/components/ui/siri-wave";
import { useNarrow } from "@/hooks/use-narrow";

/** Stages A through E, in the order the pipeline actually runs them. */
const STAGES = [
  {
    key: "A",
    name: "Code graph",
    detail:
      "tree-sitter over TypeScript and JavaScript, ESM and CommonJS alike, into Module / Symbol / CALLS / IMPORTS.",
  },
  {
    key: "B",
    name: "Dependencies",
    detail:
      "Lockfile to a resolved release graph, each edge carrying the window that version was actually resolved in.",
  },
  {
    key: "C",
    name: "Advisories",
    detail:
      "OSV in one batch call, then classified install-time or runtime — the fork that inverts the whole analysis.",
  },
  {
    key: "D",
    name: "The join",
    detail:
      "Resolve the import specifier, find the entry point, parse that package lazily, bind the export to its internal symbol.",
  },
  {
    key: "E",
    name: "Identity",
    detail:
      "Maintainer and registry provenance, so a compromised publisher is a question the graph can answer too.",
  },
];

export function HowItWorks() {
  const narrow = useNarrow();

  return (
    <section
      id="how"
      className="relative w-full overflow-hidden border-t border-border bg-background px-6 py-24 sm:px-10 md:py-32 lg:px-20"
    >
      <div className="mx-auto grid max-w-6xl gap-16 lg:grid-cols-[0.85fr_1fr] lg:items-start lg:gap-20">
        {/* The shader stands in for the traversal itself: one signal running the
            length of the graph. Purely atmospheric, and it says so by carrying
            no data — a chart that looked real but wasn't would be worse. */}
        <div className="flex flex-col items-center lg:sticky lg:top-24">
          <SiriWave
            variant="wave"
            size={narrow ? 260 : 360}
            className="rounded-3xl shadow-[0_20px_60px_rgba(0,0,0,0.6)] ring-1 ring-border"
          />
          <p className="mt-5 max-w-[22rem] text-center text-xs leading-relaxed text-muted-foreground">
            Zero LLM calls on the Track 2 critical path. Every stage below is
            deterministic, and every write goes through one batched{" "}
            <span className="font-mono text-foreground">UNWIND</span> over Bolt.
          </p>
        </div>

        <div>
          <p className="mb-4 text-xs font-medium uppercase tracking-[0.25em] text-muted-foreground">
            The pipeline
          </p>
          <h2 className="max-w-xl text-3xl font-light leading-tight tracking-tight sm:text-4xl lg:text-5xl">
            Five stages. The fourth one is{" "}
            <span className="text-primary">the whole project</span>.
          </h2>
          <p className="mt-5 max-w-xl text-[0.95rem] leading-relaxed text-muted-foreground">
            Your code says <span className="font-mono text-xs text-foreground">import &#123; merge &#125; from 'lodash'</span>.
            The advisory says &ldquo;prototype pollution in lodash&rsquo;s merge&rdquo;.
            Binding those two facts means crossing the package boundary, and
            that crossing is where every other tool stops.
          </p>

          <ol className="mt-10 flex flex-col">
            {STAGES.map((stage) => (
              <li
                key={stage.key}
                className="group grid grid-cols-[auto_1fr] gap-x-5 border-t border-border py-5 transition-colors last:border-b hover:bg-muted/30"
              >
                <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-border font-mono text-xs text-muted-foreground transition-colors group-hover:border-primary/60 group-hover:text-primary">
                  {stage.key}
                </span>
                <div className="min-w-0">
                  <h3 className="text-base font-semibold tracking-tight">
                    {stage.name}
                  </h3>
                  <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
                    {stage.detail}
                  </p>
                </div>
              </li>
            ))}
          </ol>

          <div className="mt-10 rounded-xl border border-border bg-muted/20 p-5">
            <h3 className="text-sm font-semibold">Stated limitations</h3>
            <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
              A static call graph over a dynamic language is an
              over-approximation. Handled: static ESM/TS imports, direct calls,
              re-exports, barrel files. Not handled:{" "}
              <span className="font-mono text-xs text-foreground">require()</span>{" "}
              with non-literal arguments,{" "}
              <span className="font-mono text-xs text-foreground">eval</span>,
              runtime monkey-patching, reflection-based dispatch. Where OSV gives
              a version range but no vulnerable symbol, Adit falls back to
              &ldquo;reaches the package&rsquo;s public API&rdquo; and labels the
              result as exactly that.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
