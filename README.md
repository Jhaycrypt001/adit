# Adit

**A reachability engine.** One question, over a graph:

> Does a path exist from A to B — and if so, show it. If not, say so.

Its first application: *does your code actually **reach** the vulnerable function
four levels deep in your lockfile?*

```
$ adit trace
  47 advisories affecting this repo
   3 REACHABLE
  44 not reachable (no call path from any entrypoint)

  x GHSA-9f2c  lodash@4.17.20  ->  prototype pollution in _.merge
     src/api/orders.ts:42          handleOrder()
       -> src/lib/normalize.ts:17  normalizePayload()
         -> node_modules/lodash/merge.js:12  merge()   <- vulnerable
     entrypoint: POST /orders  ·  covered by: test/orders.spec.ts
```

Not a score. **A path.**

---

## Why this exists

Security teams get hundreds of dependency alerts and can rank almost none of them.
The reason is structural: Semgrep does reachability analysis for *direct*
dependencies but does not follow the chain into transitive ones — which is exactly
where the vulnerabilities live. Kusari calls it the 95% problem.

Answering it properly is a **graph traversal** over two different graphs joined at
the package boundary: your intra-repo call graph, and the inter-package dependency
graph. Similarity search cannot do it — two functions that look alike have no call
edge between them. Recursive SQL can, miserably.

So Adit builds both graphs in [HydraDB](https://github.com/hydra-db/hydradb) and
traverses them.

## Two attack classes, opposite analysis

Most tools conflate these. Adit classifies first, then picks the query:

| Class | Example | What matters |
|---|---|---|
| **Install-time** | keyv's preinstall hook (Aug 2026), the TanStack worm | Reachability is **meaningless** — the payload runs at `npm install` whether you call the library or not. Blast radius and the temporal window are everything. |
| **Runtime** | an ordinary library-function CVE | Blast radius is **noise** — everyone depends on lodash. Reachability is everything. |

## Quick start

```bash
docker compose up -d          # HydraDB on bolt://127.0.0.1:7687
pip install -e ".[dev]"
pytest -m integration         # proves the kernel against a live engine
```

## How it works

Three query shapes, and nothing else:

- **Q1 reachability** — `algo.MSpaths` from entrypoints to vulnerable symbols, one
  server-side call instead of `sources x targets` round trips.
- **Q2 blast radius** — reverse transitive closure from a compromised release.
- **Q3 temporal validity** — did this hold *during the window the bad version was live*?

Full design, and the measured engine contract it is written against, in
[ARCHITECTURE.md](ARCHITECTURE.md).

### The engine contract is measured, not assumed

HydraDB implements "a practical OpenCypher subset" without a published feature
matrix. Adit ships the four probes that established what that subset actually is:

```bash
py scripts/probe.py       # capability check, tagged by what breaks
py scripts/surface.py     # one syntactic dimension at a time -> the spec
py scripts/semantics.py   # what the accepted statements mean
py scripts/throughput.py  # which write path is fast enough
```

Run them against any HydraDB build before trusting `ARCHITECTURE.md` — the surface
is what it is on the day. Notable findings: node `id` must be an integer while
`algo.MSpaths` matches on strings; batched edges cannot carry properties; and
`algo.MSpaths` is the **only** construct that returns a renderable path.

## Limitations

Static call graphs over a dynamic language are an over-approximation. Stated plainly:

- **Handled** — static ESM/TS imports, direct calls, re-exports, barrel files.
- **Not handled** — `require()` with non-literal arguments, `eval`, runtime
  monkey-patching, reflection-based dispatch.
- When OSV gives a version range but no vulnerable symbol, Adit falls back to
  *"reaches the package's public API"* and **labels the result as such**.
- Ingest is idempotent but not atomic — the engine has no explicit transactions. A
  partial run leaves a valid, incomplete graph and is safe to re-run.

## Prior art

[Hopper Security](https://hopper.security) sells function-level reachability for SCA.
Semgrep does it for direct dependencies. Adit's claim is not that nobody thought of
this — it is that nobody did it **graph-native, open-source, across the package
boundary, with time**.

## Licence

Adit is **Apache-2.0**. HydraDB is **AGPL-3.0** and is used *unmodified, as a network
client over Bolt* — never vendored, linked, or forked. That boundary is deliberate.
