import { useRef } from "react";
import TextCursorProximity from "@/components/ui/text-cursor-proximity";

/**
 * The claim, then the receipt.
 *
 * The two words are the entire product: a search that ran and found a path, and
 * a search that ran and found none. The terminal block beside them is a real
 * `adit trace` run against the fixture app, copied out verbatim rather than
 * mocked up -- the README holds itself to the same rule and so should the page.
 */
export function TheAnswer() {
  const containerRef = useRef<HTMLDivElement>(null);

  const proximityStyles = {
    transform: { from: "scale(1)", to: "scale(1.12)" },
    color: { from: "oklch(0.97 0.008 80)", to: "oklch(0.78 0.155 55)" },
  } as const;

  return (
    <section
      ref={containerRef}
      className="relative w-full overflow-hidden border-t border-border bg-background px-6 py-24 sm:px-10 md:py-32 lg:px-20"
    >
      <div className="mx-auto grid max-w-6xl gap-14 lg:grid-cols-[1fr_1.1fr] lg:items-center lg:gap-20">
        <div>
          <p className="mb-8 text-xs font-medium uppercase tracking-[0.25em] text-muted-foreground">
            Two answers, both earned
          </p>

          <div className="flex cursor-default flex-col uppercase leading-[0.95]">
            <TextCursorProximity
              label="Reachable"
              className="text-4xl font-black tracking-tight sm:text-6xl lg:text-7xl"
              styles={proximityStyles}
              falloff="gaussian"
              radius={110}
              containerRef={containerRef}
            />
            <TextCursorProximity
              label="Not reachable"
              className="text-4xl font-black tracking-tight sm:text-6xl lg:text-7xl"
              styles={proximityStyles}
              falloff="gaussian"
              radius={110}
              containerRef={containerRef}
            />
          </div>

          <p className="mt-8 max-w-md text-[0.95rem] leading-relaxed text-muted-foreground">
            Both are searches that completed. A third answer,{" "}
            <span className="font-mono text-xs text-foreground">unresolved</span>,
            means the search never ran because there was no symbol to search for
            &mdash; and it is reported as itself rather than folded into
            &ldquo;not reachable&rdquo;. Claiming a search that never happened is
            the one failure mode that would destroy trust in the tool.
          </p>
        </div>

        <figure className="min-w-0">
          <div className="overflow-hidden rounded-xl border border-border bg-[oklch(0.09_0.004_60)] shadow-2xl">
            <div className="flex items-center gap-2 border-b border-border px-4 py-3">
              <span className="h-2.5 w-2.5 rounded-full bg-[#ff5f57]" />
              <span className="h-2.5 w-2.5 rounded-full bg-[#febc2e]" />
              <span className="h-2.5 w-2.5 rounded-full bg-[#28c840]" />
              <span className="ml-2 font-mono text-[11px] text-muted-foreground">
                adit trace
              </span>
            </div>
            <div className="overflow-x-auto p-4 sm:p-5">
              <pre className="font-mono text-[11px] leading-relaxed sm:text-xs">
                <code>
                  <span className="text-muted-foreground">$ </span>
                  <span className="text-foreground">adit trace</span>
                  {"\n"}
                  <span className="text-muted-foreground">  5 advisories affecting this repo</span>
                  {"\n"}
                  <span className="text-primary">  2 ACTIONABLE</span>
                  {"\n"}
                  <span className="text-muted-foreground">  3 not reachable</span>
                  {"\n\n"}
                  <span className="text-destructive">  x GHSA-f23m-r3pf-42rh</span>
                  <span className="text-muted-foreground">  lodash@4.17.20</span>
                  {"\n"}
                  <span className="text-muted-foreground">     prototype pollution in </span>
                  <span className="text-foreground">`_.unset`</span>
                  {"\n\n"}
                  <span className="text-foreground">     src/api.ts:5</span>
                  <span className="text-muted-foreground">          handleOrder()</span>
                  {"\n"}
                  <span className="text-muted-foreground">       </span>
                  <span className="text-secondary">&#8594;</span>
                  <span className="text-foreground"> src/sanitise.ts:4</span>
                  <span className="text-muted-foreground">  scrubOrder()</span>
                  {"\n"}
                  <span className="text-muted-foreground">         </span>
                  <span className="text-secondary">&#8594;</span>
                  <span className="text-foreground"> unset.js:30</span>
                  <span className="text-muted-foreground">       unset()   </span>
                  <span className="text-destructive">&#8592; vulnerable</span>
                </code>
              </pre>
            </div>
          </div>
          <figcaption className="mt-3 text-xs text-muted-foreground">
            A real run, not illustrative copy &mdash; every frame in the repo&rsquo;s
            docs is held to the same standard.
          </figcaption>
        </figure>
      </div>
    </section>
  );
}
