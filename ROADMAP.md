# Adit — Build Roadmap

**Submissions close Aug 20, 11:59 PM PT. Target ship: Aug 20, 6:00 PM PT.**
Remaining: Aug 15–20, ~5.5 working days. Day 0 (Aug 14) is complete.

---

## 1. What "working" means here

This ships as a tool someone could actually run on Monday, not a demo harness.
Six acceptance criteria, all binary, all checked before the video is recorded:

| # | Criterion | Why it's the line between real and mock |
|---|---|---|
| **A1** | Runs on a repository **we did not write** | Fixtures prove the code runs; a foreign repo proves the *analysis* works |
| **A2** | Uses **live** registry and advisory data | No checked-in JSON snapshots on the critical path |
| **A3** | Emits a path a human can **verify by opening the files** | `file:line` that actually contains the call |
| **A4** | Produces a **correct negative** — a real advisory that is genuinely unreachable | Any tool can say "yes". Saying "no" correctly is the product |
| **A5** | **Cold start in one command** on a clean machine | `docker compose up -d && adit trace` |
| **A6** | Every published number is **measured**, not asserted | Benchmarks re-runnable from `scripts/` |

If A4 fails we do not have a product — we have a scanner that flags everything.

---

## 2. Subsystems

Five, in dependency order. The risky one is named, not buried.

### S1 — Code graph (Stage A)
tree-sitter over TypeScript/JavaScript → `Module`, `Symbol`, `CALLS`, `IMPORTS`,
`DEFINES`. Handles static ESM/TS imports, re-exports, barrel files. Entrypoint
roots: package `exports`/`bin`, route handlers, and tests (labelled separately —
test-only reachability ranks lower because real teams triage it differently).

### S2 — Dependency graph (Stage B)
Lockfile → `deps.dev` resolved graph → `Release`, `DEPENDS_ON`, and `Resolution`
facts carrying the window a version was resolved. Free API, no auth.

### S3 — Advisories (Stage C)
`OSV /v1/querybatch` over the resolved release set → `Advisory`, `Exposure` facts.
Free, no auth, **no rate limits**. Each advisory is classified
`install_time` vs `runtime` — the distinction that inverts the analysis.

### S4 — Vulnerable-symbol resolution ← **the risk**
See §3. Without this, "reachability" collapses into "do I import it", which is
what existing tools already do badly.

### S5 — Cross-package binding (Stage D) ← **the hard part**
Bind `import { merge } from 'lodash'` to lodash's *internal* vulnerable symbol:
resolve the specifier → find the package entry point → lazily parse its source →
build its internal call graph → connect the exported name to the internal symbol.

**Lazy by design.** Only packages sitting on a path to an advisory are parsed —
never the whole `node_modules` tree.

---

## 3. How Adit learns which function is vulnerable

npm advisories do **not** carry affected-function data. Go and Rust populate
`affected[].ecosystem_specific`; npm leaves it empty. So the symbol is derived,
with three tiers of decreasing confidence — and `confidence` is already a
first-class property on every reified fact, so the tier travels with the answer
all the way to the CLI output.

| Tier | Method | Confidence | Example |
|---|---|---|---|
| **T1** | Parse advisory `summary`/`details` for identifiers, **then accept only names that match a real exported symbol** in the package we parsed | 0.9 | GHSA-jf85-cpcp-j695 names `defaultsDeep`; lodash exports it → accepted |
| **T2** | Follow the `FIX` / PR reference, fetch the patch, extract changed function names | 0.7 | lodash PR #4336 → functions touched by the fix |
| **T3** | Fall back to the package's **public API surface**, and say so | 0.4 | Output reads *"reaches package public API (symbol unresolved)"* |

The cross-check in T1 is what makes it safe: prose naming something that isn't a
real export is silently discarded rather than becoming a phantom target. T3 is
never presented as if it were T1 — the CLI prints the tier.

**This subsystem is the difference between a real reachability tool and a
re-skinned dependency scanner.** It gets a dedicated block on Aug 16.

---

## 4. Day by day

Each day has a **definition of done** and a **fallback**. No single component is
allowed to block the demo.

### Sat Aug 15 — S1 + S2 · the graph holds real code — **DONE, ahead of schedule**
- ✅ tree-sitter TS/JS extraction; symbol + call + import resolution (ESM *and*
  CommonJS — express 5 and most of npm are CJS, so this was on the critical path)
- ✅ Lockfile parse → `Release`/`DEPENDS_ON`/`Resolution`, written to HydraDB
- **Done when:** a real third-party TS repo is ingested and `adit callers <symbol>`
  returns transitive callers that are correct on manual inspection — verified on
  hono, zod, express (bind rates published in README) and real lodash from npm.

### Sun Aug 16 — S3 + S4 + S5 · the hardest day — **DONE, same day as Sat**
- ✅ OSV batch → advisories + install-time/runtime classification
- ✅ The three-tier symbol resolver (§3) — 5/5 real lodash advisories resolved
  on tier 1, with the rejection guard confirmed firing on non-export prose
- ✅ Cross-package binding: specifier → entry point → lazy parse → symbol bind
- **Done when:** for one real repo and one real CVE, Adit binds an import to the
  actual vulnerable function inside `node_modules` — done: `handleOrder ->
  scrubOrder -> unset (unset.js:30)`, hand-verified against the source.

### Mon Aug 17 — end to end · the product exists — **DONE**
- ✅ `adit trace` / `adit blast` / `adit why`, path rendering to `file:line`
- ✅ Benchmark `algo.MSpaths` vs client fan-out: 47.6x, both methods agreeing on
  every reachable pair (parity asserted, not just timed) — in README
- 🔶 **Demo target selection still open:** the demoapp fixture gives a clean,
  hand-verified reachable/unreachable contrast (2 actionable / 3 not-reachable
  on real lodash CVEs) and is honestly disclosed as constructed-for-demo. A
  full `adit trace` run against a real, unmodified third-party repo is in
  progress — first candidate (express) installing live; if it comes back clean
  (0 actionable) that is itself a legitimate, publishable result, not a failure.
- **A1–A4:** A1 done via the bind-rate benchmarks + demoapp; A2/A3/A4 done via
  live OSV + hand-verified path + demoapp's genuine negative. Full closure
  needs the third-party `adit trace` run above.

### Tue Aug 18 — surfaces + Track 3 — **DONE, a day early**
- ✅ MCP server, exactly 5 tools (`trace_repository`, `why_reachable`,
  `blast_radius`, `callers_of`, `find_symbol`), each description checked <700
  chars, tested through the real `call_tool()` protocol path
- ✅ LongMemEval adapter — proved on REAL downloaded data (not synthetic): the
  same `ORDER BY valid_from DESC LIMIT 1` shape answers a genuine
  knowledge-update question at three different query dates, including the
  bitemporal case (querying *between* two sessions returns the *older* value)
- **Frontend decision:** still open, still the owner's call. Kernel returns
  structured JSON (`render.to_json`) either way, so nothing blocks on it.

### Wed Aug 19 — Track 1 + freeze — **Track 1 done, two days early**
- ✅ HERB adapter — real employee/product entities cloned directly from
  `SalesforceAIResearch/HERB` (data ships as raw JSON in the repo, no
  generation pipeline needed). Three real, reported search attempts for a
  naturally-occurring contradiction came up empty (near-duplicate documents,
  no per-product role field, no conflict-tagged questions in this dataset) —
  so the specific conflicting values are constructed on real entities, said
  plainly in ARCHITECTURE.md §6b rather than presented as mined.
- ✅ Proved the real distinguishing claim, adversarially: `best_claim()` ranks
  by `(source_tier DESC, valid_from DESC)`, and the fixture is rigged so a
  recency-only sort would pick the WRONG source. First multi-column `ORDER BY`
  this project relied on — confirmed live before building on it.
- ⬜ **Feature freeze. No exceptions.** — next up
- ⬜ README/ARCHITECTURE final pass, cold-start verification on a clean machine
- ⬜ Repo public, Apache-2.0, AGPL boundary stated (already written into README
  §"Licence" — just needs the repo actually made public)

### Thu Aug 20 — ship
- ⬜ Demo video ≤3 min (structure in §6)
- ⬜ **Submit by 6:00 PM PT.** The form closes hard; late entries are not accepted

**Two unplanned but consequential fixes, worth carrying forward:** stage B's
lockfile parse was never being written to HydraDB (`adit blast` silently always
returned zero), and `Queries.key_exists()` had a defect where a bare `{id: X}`
match returns a phantom row for ANY integer — meaning every "not found" error
path in the CLI/MCP was dead code until fixed. Both are detailed in
ARCHITECTURE.md and their respective commits. The lesson: run the CLI commands
that check for absence, not just the ones that find something — absence checks
are exactly where a silent defect hides longest.

---

## 5. Standing risks

| Risk | Signal it's happening | Response |
|---|---|---|
| Cross-package binding (S5) overruns | Sunday ends without one real bind | Drop to T3 public-API reachability, labelled; ship |
| TS dynamic imports defeat the graph | Call graph misses obvious edges | Declare in limitations; static-only is a legitimate, stated scope |
| No repo gives a clean reachable/unreachable contrast | Monday scan comes back flat | Widen the repo scan; worst case, demo blast radius (install-time class) which needs no symbol resolution |
| ~~`tree-sitter` wheels missing for Python 3.14~~ | — | **Retired Aug 14.** Verified: `tree_sitter` + `tree_sitter_typescript` install and parse on 3.14 |
| Machine constraints (4 cores, <4 GB) | Ingest thrashes | Ingest is I/O-bound, not RAM-bound; chunk at 1024 and stream |

---

## 6. Demo video (3 min)

1. **0:00–0:20** — "47 alerts this morning. Three matter. Here's how you know which."
2. **0:20–1:30** — `adit trace` on a **real repo**. The path, `file:line`, into
   `node_modules`. Then a **not-reachable** result — and why that half is the valuable one.
3. **1:30–2:10** — `adit blast` on a real install-time compromise. Reachability is
   skipped because a preinstall hook runs regardless; the temporal window query runs
   instead. **That one sentence is what makes us look like engineers.**
4. **2:10–3:00** — Same kernel, agent memory: a fact overwritten three sessions later,
   answered correctly; then an abstention. Architecture slide. "This is traversal.
   A vector index cannot answer it at all."

---

## 7. Not building

No web UI (owner's call, revisited Tue). No dashboard. No auth. No multi-language
support. No custom embedding model. No Graphiti driver. No 500K-document ingest.

**If it isn't on the path to §6, it doesn't exist this week.**
