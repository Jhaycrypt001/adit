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

### Measured: `algo.MSpaths` vs client-side fan-out

Answering "which of my services reach any of these advisories" the naive way is
`len(entrypoints) x len(targets)` separate queries. `algo.MSpaths` resolves the
whole batch in one server-side call. Measured on identical data, both methods
finding the identical set of reachable pairs (`py scripts/bench_traversal.py`):

| | calls | wall clock |
|---|---|---|
| `algo.MSpaths` | 1 | 0.94s |
| client fan-out | 900 | 44.5s |

**47.6x**, and the gap widens with scale — at a realistic 200 services x 47
advisories (9,400 pairs), fan-out alone projects past 7 minutes.

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

## Run on a real, unmodified repository

Not a fixture. Cloned [expressjs/express](https://github.com/expressjs/express)
at 5.2.1, installed it exactly as published, and pointed `adit trace` at it
with nothing changed:

```
express@5.2.1
  141 modules, 435 symbols, 379 internal calls, 1,688 external refs
  403 packages, 639 dependency edges, 44 direct

  4 advisories affecting this repo
  0 ACTIONABLE
  4 not reachable
```

`npm audit` flags all four. Adit traced every one of them and found no call
path from any of express's 56 entrypoints. Checking why: none of the three
implicated packages (`diff`, `serialize-javascript`, `uuid`) appear anywhere
in express's own `package.json` or source — `npm ls` places all three several
levels inside `mocha` and `nyc`, express's *test runner and coverage tool*.
Code that ships in a deployed Express app never executes any of it.

This is the ordinary case, not a cherry-picked one: most CVE noise in a real
project lives exactly here, in dev tooling nowhere near the request path. A
scanner that only checks "is the package installed" cannot tell the
difference; Adit ran a real graph search and can.

## One kernel, three tracks

Reachability, knowledge-update, and conflict-resolution turn out to be the
same query shape with a different sort key, proven on real data from each
track rather than asserted:

| Track | Question | Ranking | Proven on |
|---|---|---|---|
| **2A** (primary) | Does my code reach this? | path exists / does not | real lodash, express, a constructed demo app |
| 3 | What's true now, given an update? | `valid_from` (recency) | real LongMemEval session pair |
| 1 | Which source do I trust? | `source_tier`, then `valid_from` | real HERB entities |

Track 1's adversarial test rigs timestamps so a recency-only sort gives the
*wrong* answer — a stale Slack message can't outrank a document it never
superseded, on authority alone, regardless of which is newer. Full detail,
including the honest negative results from searching HERB for a
naturally-occurring contradiction, is in `ARCHITECTURE.md` §6a–6b.

## Limitations

Static call graphs over a dynamic language are an over-approximation. Stated plainly,
with measured numbers rather than adjectives.

**Handled** — ESM `import`/`export`, CommonJS `require`/`module.exports`, barrel
files and `export *`, aliased re-exports, `this.method()` chains, namespace imports,
constructor-typed locals (`const s = new Svc(); s.run()`), and module-scope callables
produced by factories (`var merge = createAssigner(...)` — how much of npm is written).

**Not handled** — `require()` with non-literal arguments, `eval`, runtime
monkey-patching, and reflection-based dispatch.

**Measured call-site binding** (`py scripts/bench_extract.py <repo>`):

| Repo | Modules | Symbols | Bound | Unbound, dominated by |
|---|---|---|---|---|
| hono 4.13 | 383 | 2,492 | 16.5% | member calls on untyped receivers |
| express 5.2 | 141 | 446 | 18.5% | member calls on untyped receivers |
| lodash 4.17 | 1,046 | 3,708 | 37% | internal `_`-prefixed helpers |

**Read that number correctly.** The unbound majority is `res.send()`, `arr.map()`,
`console.log()` — calls on receivers whose type needs a TypeScript type checker, and
which overwhelmingly terminate in built-ins rather than leading into dependencies.
What Adit must bind for reachability to work is the **package boundary**, and those
arrive as direct or namespace imports, which are bound: 1,688 external refs across 43
packages in express, 1,258 across 57 in hono.

Adit reports its own bind rate and the reasons for every unbound call. A tool that
claimed 100% here would be lying.

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
