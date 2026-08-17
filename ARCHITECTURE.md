# Adit — Architecture

Adit is a **reachability engine**. It answers one question over a graph:

> **Does a path exist from A to B — and if so, show it. If not, say so.**

Its primary application is transitive vulnerability reachability: *does my code
actually reach the vulnerable function four levels deep in my lockfile?* The same
primitive answers enterprise-knowledge and agent-memory questions, which is why
one kernel serves all three hackathon tracks without special-casing the query layer.

---

## 0. How this document was produced

Everything below is written against a **measured** capability surface, not the
README's description of one. HydraDB documents itself as implementing "a practical
OpenCypher subset" without publishing a feature matrix, so before writing any
dependent code we mapped the subset empirically:

| Script | Purpose |
|---|---|
| `scripts/probe.py` | First-pass capability check, tagged by which part of Adit breaks |
| `scripts/surface.py` | Varies one syntactic dimension at a time; emits the executable-form spec |
| `scripts/semantics.py` | What the executable statements *mean* (node identity, path payloads) |
| `scripts/throughput.py` | Which write path is fast enough to ingest a real repository |

Two rounds of shape-guessing failed 20/23 and 22/23. The engine's error text turned
out to be a precise specification rather than a wall, and §1 is the result. **Run
these against any HydraDB build before trusting this document** — the surface is
what it is on the day, not what a README says.

---

## 1. The measured HydraDB contract

These are hard constraints. Every design decision downstream exists because of one.

### Writes

| Rule | Consequence for Adit |
|---|---|
| `CREATE` supports **one-hop edge patterns only** — no standalone nodes, no 2-hop chains | Nodes are born via UNWIND upsert; edges via one-hop CREATE |
| `CREATE` **attaches by `id`** — repeat ids upsert the node, append the edge, and do **not** clobber existing properties | Ingest emits edges directly; no pre-pass needed |
| Write clauses are **terminal** — nothing may follow `CREATE`/`MERGE`/`SET` | Writers get no return value; verification is a separate read |
| `MATCH ... CREATE` is rejected by the mutation engine | Cannot connect two pre-existing nodes by lookup; must use the id-bearing CREATE form |
| **Explicit transactions are not supported** ("use auto-commit RUN queries") | No multi-statement atomicity. Ingest must be idempotent and re-runnable |
| Batch size is capped at **1024 rows** by admission control | Every batch chunks at 1024 |

### The property rule that drives the whole schema

| Form | Properties allowed |
|---|---|
| `UNWIND $rows AS r MERGE (n {id: r.id}) SET n:Label, n.p = r.p` | **Full node properties** — ~14,500 nodes/sec |
| `UNWIND $rows AS r CREATE (a {id: r.src})-[:T]->(b {id: r.dst})` | **`id` only.** Edges carry **no properties** — ~10,000 edges/sec |
| `CREATE (a {id: 1})-[:T {p: 1}]->(b {id: 2})` | Full edge properties — but **~5–10 edges/sec** |

Concurrency does not help: 1, 4 and 8 parallel sessions all measured ~10 edges/sec
on the single-write path, consistent with object-store CAS writer coordination.

### Reads

| Rule | Consequence |
|---|---|
| A property named `id` **must be an integer** | All identity is a 63-bit hash; the human-readable key is a separate string property |
| Variable-length `MATCH` **requires a fixed integer source id** | Names are resolved to ids client-side, then traversed |
| Variable-length traversal is **forward-only** | Reverse closure needs materialised inverse edges — see below |
| Cannot **bind or filter relationships inside** a variable-length match | Temporal filtering cannot happen mid-traversal (see §3) |
| `RETURN` supports only `<binding>.<property>` or `count(*)` | No `nodes(p)`, `length(p)`, `min()`, `count(n)`, or whole-node returns |
| Composite parameters are **UNWIND-only** | No `WHERE x IN $ids`, no `SET n += $map` |
| Undirected patterns rejected | Direction is always explicit |
| No index DDL at all (`CREATE INDEX`, `SHOW INDEXES`, `db.indexes()`) | Indexing is engine/config-managed, not application-managed |

### Reverse closure has no direct expression

Both reverse spellings of a variable-length match are rejected — the anchor must
sit at the **traversal source**, and reversing the arrow moves it to the unbound end:

```cypher
MATCH (bad {id: X})<-[:DEPENDS_ON*1..5]-(d)   -- rejected
MATCH (d)-[:DEPENDS_ON*1..5]->(bad {id: X})   -- rejected
MATCH (s {id: X})-[:DEPENDED_ON_BY*1..5]->(d) -- works
```

Single-hop reverse (`<-[:R]-`, no `*`) is fine; only transitive reverse is not.

**Chaining two single-hop reverse edges from one fixed anchor is a separate,
silent trap.** `(a {id: X})<-[:R1]-(b)<-[:R2]-(c)` executes without error and
returns zero rows even when the data matches, while the semantically
equivalent split-MATCH form fails identically -- both confirmed with
`scripts/chain_direction.py`. `(a {id: X})<-[:R1]-(b)-[:R2]->(c)`, one reverse
hop followed by one forward hop, works. This is the one finding in this whole
contract that gives **no error text at all** to catch it — a two-reverse-hop
chain simply looks like "no matches", which is why `queries.py` documents each
multi-hop query's direction reasoning inline, and why `exposed_services()` has
a paired positive/negative integration test rather than relying on the query
executing without exception.

Since blast radius **is** transitive reverse closure, Adit materialises the inverse
edge at ingest (`schema.INVERSE_OF`) and traverses it forward. Batched edges cost
~10,000/sec, so this is the cheap answer rather than a compromise — and it buys
backward slicing for free: *what transitively calls this function*, i.e. what breaks
if I change it.

### A bare id match is not a safe existence check

`MATCH (n {id: X}) RETURN n.key` returns **one row with every property null**
for an `X` that was never written — not zero rows. Confirmed against five
fresh, cryptographically random 62-bit integers guaranteed never to have been
used as a node id: every single one "matched". No error, no warning — the
result silently looks exactly like a real (if oddly empty) node.

The defect is narrow but exactly hits the one query whose entire job is
"does this exist": `Queries.key_exists()`, used to validate a CLI/MCP argument
before running a real query against it. Every *traversal* query in `queries.py`
is unaffected — `MATCH (n {id: X})-[:REL]->(m)` from a nonexistent `X`
correctly returns zero rows in every one of them, confirmed across 79 passing
tests before this was found. The gap is specifically a bare vertex-only
pattern with no relationship attached, consistent with the engine treating the
id space as dense and pre-allocated (plausible given the CSC/GraphBLAS
topology index) rather than sparse.

**Fix:** `WHERE n.key = n.key`. Cypher's three-valued logic makes `NULL = NULL`
evaluate to false rather than true, which filters the phantom row out without
needing `IS NOT NULL` (not in the supported surface — see below) or a label
filter (which would work too, but `key_exists()` is intentionally label-agnostic
since it validates Service, Release and Symbol keys alike).

`WHERE ... IS NOT NULL` is rejected outright: `"WHERE currently supports
boolean combinations of property comparisons"`.

### The one thing that returns a renderable path

`RETURN` cannot project `nodes(p)`. But `algo.MSpaths` yields a **fully hydrated
`Path`** — `.nodes`, `.relationships`, `.start_node`, `.end_node`, with node
properties intact:

```
<Path start=<Node element_id='900010' properties={'name': 'p0'}>
      end=<Node element_id='900014' properties={'name': 'p4'}> size=4>
  -> rendered:  p0 -> p1 -> p2 -> p3 -> p4
```

**This makes HydraDB's native procedure structurally load-bearing, not decorative.**
Showing the call path file-by-file *is* the product, and `algo.MSpaths` is the only
way to get one. Note it matches on a **string** property (`sourceValues must be a
list of strings`) while node identity is an integer — so `key` and `id` are both
required on every node.

---

## 2. Graph model

### Identity

Every node has:

- `id` — **integer**, `blake2b(canonical_key)` truncated to 63 bits. Required by the engine.
- `key` — **string**, the canonical human-readable identity. Required by `algo.MSpaths`.

Collision risk at 63 bits is negligible at our scale (~10⁵–10⁶ nodes) and hash
collisions are detectable at ingest by comparing `key`.

### Two classes of edge, and why

The engine forces a choice: an edge is either **fast and bare** or **slow and
propertied**. Rather than compromise, Adit splits by nature of the fact:

**Class 1 — topology edges.** High volume, timeless, batched, propertyless.

`CALLS` · `IMPORTS` · `DEFINES` · `EXPORTS` · `DEPENDS_ON` · `MAINTAINS` · `ABOUT`

A call graph is a **snapshot of one commit**. It has no independent lifetime, so it
loses nothing by being timeless. ~100k edges ingest in ~10 seconds.

**Class 2 — temporal facts, reified as nodes.** Low volume, propertied, upserted.

A fact that has a lifetime becomes a first-class node carrying the full quad:

```
(Service)-[:SUBJECT]->(Resolution)-[:OBJECT]->(Release)
                          │
                          ├─ valid_from    when it became true
                          ├─ valid_to      when it stopped (MAX if still true)
                          ├─ observed_at   when we learned it
                          ├─ source        provenance
                          └─ confidence
```

Reified fact types: `Resolution` (lockfile resolved a version during a window),
`Exposure` (advisory affected a release), `Claim` (an assertion about an entity),
`Observation` (an episode asserted a claim).

**This is a better model than putting the quad on edges, not a workaround.** A
reified fact is queryable, can carry provenance and confidence, can be superseded,
and can hold multiple independent observations of the same relationship. It is the
standard temporal-graph event-node pattern — the engine's constraint pushed us onto
the correct design.

Cost: traversals through reified facts are two hops instead of one. Budget `maxLen`
accordingly.

### Node labels

| Label | Purpose | Track |
|---|---|---|
| `Symbol` | function / method / class | 2 |
| `Module` | file or module | 2 |
| `Package` / `Release` | package, and a specific version | 2 |
| `Service` | deployable unit with a lockfile | 2 |
| `Advisory` | CVE / GHSA, classified `install_time` \| `runtime` | 2 |
| `Identity` | maintainer / person — shared entity-resolution node | 2 + 1 |
| `Entity` | enterprise entity | 1 |
| `Episode` | session or document | 1 + 3 |
| `Claim` | reified assertion | 1 + 3 |
| `Resolution` / `Exposure` / `Observation` | reified temporal facts | all |

---

## 3. Query strategy

### Q1 — reachability (the product)

Resolve entrypoints and vulnerable symbols to `key` strings client-side, then:

```cypher
CALL algo.MSpaths({
  sourceLabel: 'Symbol', sourceProperty: 'key',
  sourceValues: [...entrypoint keys...],
  targetValues: [...vulnerable symbol keys...],
  relTypes: ['CALLS'], relDirection: 'outgoing',
  maxLen: 12, pathCount: 3, resultLimit: 500
}) YIELD path RETURN path
```

One server-side call replaces `entrypoints × advisories` client round-trips. Paths
come back hydrated and render directly to `file:line` output.

**Composite parameters are UNWIND-only, so the value lists must be inlined as
literals.** `adit.graph.cypher` builds them with strict escaping — see §5.

### Q2 — blast radius (reverse transitive closure)

Anchored on a fixed integer id, traversing reversed:

```cypher
MATCH (bad {id: $releaseId})<-[:DEPENDS_ON*1..10]-(dependent)
RETURN DISTINCT dependent.key AS key
```

### Q3 — temporal validity

Because relationships cannot be filtered inside a variable-length match, the
temporal predicate lands on the **reified fact node**, where it is fully supported:

```cypher
MATCH (s:Service {id: $serviceId})-[:SUBJECT]->(r:Resolution)-[:OBJECT]->(rel:Release)
WHERE r.valid_from < $windowEnd AND r.valid_to > $windowStart
RETURN rel.key AS release, r.valid_from AS from, r.source AS source
```

Where a temporal filter must apply to a path already returned by `algo.MSpaths`,
it is applied **client-side** over `path.relationships` — the payload carries what
is needed.

### Abstention

Empty result means **no path exists**, which is a fact, not a guess. Adit reports
`NOT_REACHABLE` together with the frontier it explored. It never fabricates. The
negative case is verified in the test suite alongside the positive one, because a
false "reachable" is the failure mode that destroys trust in the tool.

---

## 4. Ingest pipeline

| Stage | Input | Emits | LLM cost |
|---|---|---|---|
| **A · code** | repo → tree-sitter (TS/JS) | `Module`, `Symbol`, `CALLS`, `IMPORTS`, `DEFINES` | none |
| **B · deps** | lockfile → deps.dev `:dependencies` | `Release`, `DEPENDS_ON`, `Resolution` | free API |
| **C · advisories** | OSV `/v1/querybatch` | `Advisory`, `Exposure` | free, no rate limit |
| **D · the join** | lazy parse of affected package in `node_modules` | `EXPORTS`, vulnerable-symbol binding | none |
| **E · identity** | ecosyste.ms maintainers | `Identity`, `MAINTAINS` | free API |

**Zero LLM calls on the critical path.** That is what makes the timeline viable.

Every stage is **idempotent** — mandatory, since explicit transactions do not exist
and a failed run must be safe to repeat. Nodes upsert by `id`; edges are appended by
the id-bearing CREATE form.

### Stage D is the hard part

Your code says `import { merge } from 'lodash'`. The advisory says "prototype
pollution in lodash's `merge`". Binding those requires crossing the package
boundary: resolve the specifier → find the package entry point → parse *its* source
→ build *its* internal call graph → bind the exported name to the internal symbol.

Scope discipline: parse **only** dependencies on a path to an advisory, never the
whole tree; **TypeScript/JavaScript only**.

---

## 5. Code layout

```
src/adit/
  graph/
    driver.py     connection, retry, chunked execution (1024 cap)
    ids.py        blake2b -> 63-bit int; key <-> id resolution
    schema.py     labels, edge classes, reified fact types
    writer.py     upsert_nodes() / create_edges() / upsert_facts()
    cypher.py     literal-list inlining with strict escaping
    queries.py    Q1 / Q2 / Q3 -- the entire query layer
  ingest/         stages A-E
  classify.py     install-time vs runtime advisory triage
  render.py       Path -> file:line output
  cli.py          adit trace | blast | why
scripts/          the four capability probes (see §0)
```

### Why `cypher.py` exists

Composite parameters are UNWIND-only, so `algo.MSpaths` value lists **must** be
inlined into the query text. That is a string-injection surface, and package names
and symbol keys come from untrusted registry data. All inlining goes through one
audited function that rejects any key not matching a strict allowlist pattern.
Nothing else in the codebase builds Cypher by concatenation.

---

## 6. Why a graph, and why HydraDB

- **Vector search cannot do this at all.** Similarity is not reachability; two
  functions that look alike have no call edge between them.
- **Relational is miserable.** Recursive CTEs across two heterogeneous graphs — the
  intra-repo call graph and the inter-package dependency graph — joined at the
  symbol boundary over millions of edges.
- **HydraDB earns its place** three ways: CSC/GraphBLAS topology indexes for the
  closure; `algo.MSpaths` for server-side batch path resolution, which is the only
  route to a renderable path; and object-storage economics that make retaining every
  historical snapshot affordable — which is what makes *"was this reachable last
  Tuesday?"* a question you can afford to ask at all.

---

## 6a. Track 3 adapter: the bitemporal claim proven on a second domain

`ingest/memory.py` maps LongMemEval chat sessions onto the same kernel, to
prove the central claim rather than assert it: Q3's exact shape -- a range
filter on a bitemporal quad, `ORDER BY valid_from DESC LIMIT 1` -- answers
Track 2's "was this lockfile resolution live during the compromise window"
and Track 3's "what did I say my personal best was" with the same primitive.

One deliberate deviation from the original design: **`Claim` nodes carry their
own `valid_from`/`valid_to`/`observed_at`/`source`/`confidence` directly**,
rather than through a separate reified `Fact` indirection with `SUBJECT`/
`OBJECT` edges. The reason is §3's direction-chaining trap: answering "the
current value for this owner" through a `Fact` indirection needs a three-hop
mixed-direction chain (`Entity -> Episode <- SUBJECT - Fact -> OBJECT ->
Claim`), and only two-hop chains have been proven safe. Putting the quad
directly on `Claim` and connecting it with one `Entity -[:ASSERTS]-> Claim`
edge keeps the query to a single fixed-source hop with a property filter --
a shape already exercised by every other query in this file. The lesson
generalises: prefer the fact-carrying node be reachable in one hop from
whatever you will anchor the query on, even if that means duplicating the
quad's shape across two node types instead of centralising it in one.

Extraction is real and narrow, not fabricated to fit the benchmark: one
pattern family (a named quantity with a value and optional unit) run against
raw session text, with **no access to the dataset's own answer-key labels** --
using those would make the demonstration circular. Verified against a real
downloaded item (`tests/fixtures/longmemeval_sample.json`, a genuine
knowledge-update case: a runner states a personal-best 5K time of 27:12,
then a new personal best of 25:50 two sessions later). The extractor labels
the subject "time", not "personal best" -- the words "personal best" and the
number are not adjacent in the real sentence, and the pattern anchors on the
nearest preceding noun. This is reported honestly rather than rounded up: the
value extracted is exactly right, and the test fixture asserts the subject
label the heuristic actually produces, not the one that would look best.

The reachability engine's answer, queried as of three different dates,
against the same two real sessions:

| Query date | Answer | Why |
|---|---|---|
| before either session | none | the query-level abstention case: no claim yet exists |
| between the two sessions | `27:12` | what was true *then*, not what became true later |
| after both sessions | `25:50` | the current value -- the update took effect |

The middle row is the one that proves bitemporal, not merely "latest wins":
getting it backwards would mean Adit can only state the present, not history.

## 7. Stated limitations

Static call graphs over a dynamic language are an **over-approximation**. Declared
plainly, because hidden limits get found:

- **Handled:** static ESM/TS imports, direct calls, re-exports, barrel files.
- **Not handled:** `require()` with non-literal arguments, `eval`, runtime
  monkey-patching, reflection-based dispatch.
- When OSV supplies a version range but no vulnerable symbol, Adit falls back to
  *"reaches the package's public API"* and **labels the result as such** — never
  silently.
- Ingest is idempotent but **not atomic**; the engine has no explicit transactions.
  A partial run leaves a valid, incomplete graph and is safe to re-run.

## 8. Licensing boundary

HydraDB is **AGPL-3.0**. Adit connects to it **as a network client over Bolt** and
ships its own code, so Adit is not a derivative work. HydraDB source is never
vendored, linked, or modified — the container is used unmodified. Adit ships under
**Apache-2.0**. This boundary is deliberate and load-bearing; do not cross it.
