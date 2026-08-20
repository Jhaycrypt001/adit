import { useEffect, useMemo, useState } from "react";
import { CopyButton } from "@/components/console/CopyButton";

const REPO = "https://github.com/Jhaycrypt001/adit";

interface Section {
  id: string;
  title: string;
  body: React.ReactNode;
}

function Code({ children, lang }: { children: string; lang?: string }) {
  return (
    <div className="relative my-4 overflow-hidden rounded-lg border border-border bg-[oklch(0.09_0.004_60)]">
      <div className="flex items-center justify-between border-b border-border px-3 py-1.5">
        <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
          {lang ?? "shell"}
        </span>
        <CopyButton value={children.trim()} label="copy" />
      </div>
      <pre className="overflow-x-auto p-3">
        <code className="font-mono text-xs leading-relaxed text-foreground">
          {children.trim()}
        </code>
      </pre>
    </div>
  );
}

function P({ children }: { children: React.ReactNode }) {
  return <p className="my-3 text-sm leading-relaxed text-muted-foreground">{children}</p>;
}

function K({ children }: { children: React.ReactNode }) {
  return (
    <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[0.85em] text-foreground">
      {children}
    </code>
  );
}

function H3({ children }: { children: React.ReactNode }) {
  return <h3 className="mt-7 text-base font-semibold tracking-tight">{children}</h3>;
}

const SECTIONS: Section[] = [
  {
    id: "start",
    title: "Getting started",
    body: (
      <>
        <P>
          Adit needs HydraDB running. Everything ships in one compose file, so the
          whole stack is one command.
        </P>
        <Code>{`git clone ${REPO} && cd adit
docker compose up -d          # HydraDB :7687, adit-api :8420
pip install -e .`}</Code>
        <P>
          Then run it against the worked example, which is built so both halves of
          an answer are visible — one advisory your code can reach, three it cannot.
        </P>
        <Code>{`npm --prefix examples/demo-app install --ignore-scripts
adit trace examples/demo-app`}</Code>
        <P>
          You should see <K>2 ACTIONABLE</K> and <K>3 not reachable</K>. That single
          command exercises the entire pipeline: parse, lockfile, advisories,
          cross-package binding, traversal.
        </P>
        <H3>The web console</H3>
        <Code>{`cd frontend && npm install && npm run dev   # http://localhost:5173`}</Code>
        <P>
          Point it at a different API with <K>VITE_API_URL</K> in{" "}
          <K>frontend/.env</K>.
        </P>
      </>
    ),
  },
  {
    id: "cli",
    title: "CLI",
    body: (
      <>
        <P>Three commands, mirroring the three query shapes.</P>
        <Code>{`adit trace <path>              # every advisory, answered
adit blast <pkg>@<version>     # reverse transitive closure
adit why <source> <target>     # explain one reachability answer

  --max-len N     traversal depth cap (default 12)
  --offline       skip network calls that only refine symbol confidence
  --json          machine-readable output
  --no-color      plain text, for piping or recording`}</Code>
        <P>
          <K>--json</K> emits the same payload the HTTP API returns, so anything
          built against one works against the other.
        </P>
      </>
    ),
  },
  {
    id: "api",
    title: "HTTP API",
    body: (
      <>
        <P>
          Runs on <K>:8420</K>. Built to be safe to expose publicly: the scan
          endpoint takes a GitHub URL rather than a server-side filesystem path.
        </P>
        <H3>POST /scan</H3>
        <Code lang="json">{`{
  "repo_url": "https://github.com/owner/repo",
  "subdir": "frontend",      // optional: where package.json lives
  "max_len": 12,             // optional
  "offline": false           // optional
}`}</Code>
        <P>
          Returns the full report plus a <K>scan_id</K>. Pass that id to the other
          endpoints to ask follow-up questions scoped to the same scan.
        </P>
        <H3>GET /blast/&#123;package&#125;@&#123;version&#125;</H3>
        <P>
          Query params: <K>scan_id</K>, <K>max_len</K>. Returns the transitive
          dependent set and which services resolved that exact release.
        </P>
        <H3>GET /why</H3>
        <P>
          Query params: <K>source</K>, <K>target</K> (both exact canonical keys),{" "}
          <K>scan_id</K>, <K>max_len</K>. Deliberately will not resolve bare names
          — silently matching the wrong symbol over a public surface is worse than
          requiring precision. Keys come from a prior scan&rsquo;s{" "}
          <K>paths[].key</K>.
        </P>
        <H3>GET /health</H3>
        <P>
          Is HydraDB reachable over Bolt right now. Call it before offering a scan.
        </P>
        <H3>Limits</H3>
        <P>
          5 scans per 10 minutes per IP, and 4 concurrent scans per process — past
          that it sheds with <K>503</K> and a <K>Retry-After</K> rather than
          starving the whole API, since a scan is slow and synchronous.
        </P>
      </>
    ),
  },
  {
    id: "mcp",
    title: "MCP server",
    body: (
      <>
        <P>
          <K>adit-mcp</K> speaks stdio MCP. Five tools, kept deliberately few —
          teams routinely lose a fifth to two-thirds of a context window to tool
          schemas before an agent does any real work.
        </P>
        <Code lang="json">{`{
  "mcpServers": {
    "adit": { "command": "adit-mcp" }
  }
}`}</Code>
        <P>
          Tools: <K>trace_repository</K>, <K>why_reachable</K>, <K>blast_radius</K>,{" "}
          <K>callers_of</K>, <K>find_symbol</K>. Point Claude Code or Cursor at it
          and ask whether a repo reaches a given advisory without leaving the
          editor.
        </P>
      </>
    ),
  },
  {
    id: "model",
    title: "How it works",
    body: (
      <>
        <P>
          Five ingest stages, then one of three queries depending on what class of
          advisory it is.
        </P>
        <H3>Ingest</H3>
        <P>
          <strong className="text-foreground">A · code</strong> — tree-sitter over
          TS/JS, ESM and CommonJS, into Module / Symbol / CALLS / IMPORTS.
          <br />
          <strong className="text-foreground">B · deps</strong> — lockfile to a
          resolved release graph, each edge carrying the window that version was
          resolved in.
          <br />
          <strong className="text-foreground">C · advisories</strong> — OSV in one
          batch call, classified install-time or runtime.
          <br />
          <strong className="text-foreground">D · the join</strong> — resolve the
          import specifier, find the package entry point, parse it lazily, bind the
          export to its internal symbol. This is the hard part.
          <br />
          <strong className="text-foreground">E · identity</strong> — maintainer and
          registry provenance.
        </P>
        <H3>The two attack classes</H3>
        <P>
          They need opposite analysis, and conflating them is the mistake most tools
          make. For an <strong className="text-foreground">install-time</strong>{" "}
          compromise the payload already ran at <K>npm install</K>, so reachability
          is meaningless and blast radius plus the temporal window is everything.
          For an ordinary <strong className="text-foreground">runtime</strong> CVE
          blast radius is noise — everyone depends on lodash — and reachability is
          everything.
        </P>
        <H3>Three answers, not two</H3>
        <P>
          <K>reachable</K> and <K>not_reachable</K> are both searches that
          completed. <K>unresolved</K> means the search never ran, because there was
          no symbol to search for. Reporting that as &ldquo;not reachable&rdquo;
          would claim a search that never happened, so it is never folded in.
        </P>
      </>
    ),
  },
  {
    id: "limits",
    title: "Limitations",
    body: (
      <>
        <P>
          A static call graph over a dynamic language is an over-approximation, and
          declaring that is more useful than hiding it.
        </P>
        <P>
          <strong className="text-foreground">Handled:</strong> static ESM/TS
          imports, direct calls, re-exports, barrel files, class method dispatch.
        </P>
        <P>
          <strong className="text-foreground">Not handled:</strong> <K>require()</K>{" "}
          with non-literal arguments, <K>eval</K>, runtime monkey-patching,
          reflection-based dispatch.
        </P>
        <P>
          Where OSV gives a version range but no vulnerable symbol, Adit falls back
          to &ldquo;reaches the package&rsquo;s public API&rdquo; and labels the
          result as exactly that rather than presenting it as a precise hit.
        </P>
        <P>
          <strong className="text-foreground">Storage grows without bound.</strong>{" "}
          HydraDB has no expiry mechanism and nothing deletes scan data, so a
          long-lived public deployment accumulates. That is a known limitation, not
          something this project claims to have solved.
        </P>
        <P>
          <strong className="text-foreground">HydraDB&rsquo;s local storage backend</strong>{" "}
          can start rejecting every write after sustained use, logging{" "}
          <K>PutMode::Update not yet implemented by LocalFileSystem</K>. It is an
          upstream limitation of its dev-mode storage path, not an Adit defect —{" "}
          <K>docker compose down -v &amp;&amp; docker compose up -d</K> clears it.
        </P>
      </>
    ),
  },
  {
    id: "deploy",
    title: "Deploying",
    body: (
      <>
        <H3>Frontend</H3>
        <P>
          A static Vite build — any static host works. On Vercel, set the root
          directory to <K>frontend</K> and add one environment variable,{" "}
          <K>VITE_API_URL</K>, pointing at your API.
        </P>
        <Code>{`# from the repo root
vercel --cwd frontend`}</Code>
        <P>
          <K>VITE_API_URL</K> is read at <em>build</em> time, so changing it means
          redeploying rather than restarting. It also has to be <K>https</K> — a
          browser blocks plain-HTTP requests from an HTTPS page, and the console
          reports that as an unreachable API with no obvious cause.
        </P>
        <H3>Backend</H3>
        <P>
          The API clones repositories, runs <K>npm install</K>, and needs a
          persistent volume for HydraDB. That rules out serverless: a scan takes
          40&ndash;90 seconds and needs disk, and functions have neither. Use a
          container host — Railway, Fly.io, Render, or any VPS running the compose
          file as-is — with two services, HydraDB and the API.
        </P>
        <P>
          The API reads <K>PORT</K> if the platform injects one, so it needs no
          port configuration. The setting most people get wrong is{" "}
          <K>GRAPH_ADVERTISED_BOLT_ADDR</K>: it is the address HydraDB hands back
          to clients, correct as <K>127.0.0.1</K> under compose and wrong as soon
          as HydraDB is a separate service, where it must be the private hostname
          the API dials.
        </P>
        <P>
          Full settings, sizing and the failure modes worth knowing are in{" "}
          <a
            href={`${REPO}/blob/main/DEPLOY.md`}
            target="_blank"
            rel="noreferrer"
            className="text-primary underline-offset-4 hover:underline"
          >
            DEPLOY.md
          </a>
          .
        </P>
        <P>
          Without a backend the console still loads and explains exactly which
          command starts one, so the site is useful either way.
        </P>
      </>
    ),
  },
];

/**
 * Documentation, in the app rather than a separate site.
 *
 * It ships with the frontend, so a Vercel deploy publishes the docs and the
 * console together and neither can drift from the other's version.
 */
export function Docs({ onBack }: { onBack: () => void }) {
  const [active, setActive] = useState(SECTIONS[0].id);
  const ids = useMemo(() => SECTIONS.map((s) => s.id), []);

  // Highlight whichever section is currently under the top of the viewport.
  useEffect(() => {
    const onScroll = () => {
      let current = ids[0];
      for (const id of ids) {
        const el = document.getElementById(id);
        if (el && el.getBoundingClientRect().top <= 140) current = id;
      }
      setActive(current);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [ids]);

  return (
    <div className="min-h-screen w-full bg-background">
      <div className="mx-auto max-w-6xl px-6 pb-40 pt-12 sm:px-8">
        <header className="mb-10">
          <button
            type="button"
            onClick={onBack}
            className="mb-2 text-xs text-muted-foreground transition hover:text-foreground"
          >
            ← Back
          </button>
          <h1 className="text-3xl font-semibold tracking-tight">Documentation</h1>
          <p className="mt-2 max-w-xl text-sm leading-relaxed text-muted-foreground">
            Adit is a reachability engine. Everything below is one question asked
            over a graph: does a path exist from A to B, and what is it?
          </p>
        </header>

        <div className="grid gap-10 lg:grid-cols-[13rem_1fr] lg:gap-14">
          <nav className="lg:sticky lg:top-12 lg:self-start">
            <ul className="flex flex-wrap gap-x-4 gap-y-1 lg:flex-col lg:gap-y-0.5">
              {SECTIONS.map((s) => (
                <li key={s.id}>
                  <a
                    href={`#docs-${s.id}`}
                    onClick={(e) => {
                      e.preventDefault();
                      document.getElementById(s.id)?.scrollIntoView({ behavior: "smooth" });
                    }}
                    className={`block py-1 text-sm transition ${
                      active === s.id
                        ? "text-foreground"
                        : "text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    {s.title}
                  </a>
                </li>
              ))}
              <li className="mt-4 lg:mt-6">
                <a
                  href={REPO}
                  target="_blank"
                  rel="noreferrer"
                  className="block py-1 text-sm text-muted-foreground transition hover:text-foreground"
                >
                  Source ↗
                </a>
              </li>
            </ul>
          </nav>

          <main className="min-w-0">
            {SECTIONS.map((s) => (
              <section key={s.id} id={s.id} className="mb-14 scroll-mt-24">
                <h2 className="border-b border-border pb-2 text-xl font-semibold tracking-tight">
                  {s.title}
                </h2>
                {s.body}
              </section>
            ))}
          </main>
        </div>
      </div>
    </div>
  );
}
