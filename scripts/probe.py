"""Capability probe for HydraDB.

Adit's ingest and query layers assume a specific slice of OpenCypher. HydraDB
documents itself as implementing "a practical OpenCypher subset" without
publishing a feature matrix, so we establish one empirically before writing
anything that depends on it.

Round 1 of this probe failed 20/20 and the error messages turned out to be a
precise spec rather than a wall. What they told us, and what this round encodes:

  * a property literally named `id` must be an INTEGER (50N42)
  * composite parameters (lists/maps) are ONLY valid as an `UNWIND` source --
    no `WHERE x IN $ids`, no `SET n += $map`
  * write clauses are TERMINAL -- nothing may follow CREATE/MERGE/SET
  * the supported upsert is exactly `UNWIND ... MERGE by id ... SET`
  * indexes use the legacy `CREATE INDEX ON :Label(prop)` form

Each probe is tagged with the part of Adit that breaks if it fails, so a red
line translates into a design change rather than a mystery.

    py scripts/probe.py [bolt://127.0.0.1:7687] [token]
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from typing import Any, Callable

from neo4j import GraphDatabase

CRITICAL = "critical"  # no workaround; architecture changes
IMPORTANT = "important"  # workaround exists but costs time
OPTIONAL = "optional"  # nice to have

L = "Pb"  # probe node label; suffixed with a run-unique int


@dataclass
class Result:
    name: str
    tier: str
    impact: str
    ok: bool
    detail: str = ""
    millis: float = 0.0


@dataclass
class Probe:
    name: str
    tier: str
    impact: str
    run: Callable[[Any], Any]
    verify: Callable[[Any], bool]


def build_probes(label: str) -> list[Probe]:
    def q(session, cypher, **params):
        return list(session.run(cypher, **params))

    def truthy(rows):
        return bool(rows)

    def ran(_rows):  # write clauses are terminal: success == no exception
        return True

    p: list[Probe] = []
    add = lambda *a: p.append(Probe(*a))  # noqa: E731

    # ---- writes must be terminal -------------------------------------------
    add(
        "CREATE node, terminal (no RETURN)",
        CRITICAL,
        "all ingest",
        lambda s: q(s, f"CREATE (n:{label} {{id: 1, name: 'alpha', v: 10}})"),
        ran,
    )
    add(
        "MATCH by integer id + RETURN",
        CRITICAL,
        "all queries",
        lambda s: q(s, f"MATCH (n:{label} {{id: 1}}) RETURN n.name AS name"),
        lambda rows: rows and rows[0]["name"] == "alpha",
    )
    add(
        "MERGE by id + SET, terminal",
        CRITICAL,
        "re-runnable ingest (the documented upsert shape)",
        lambda s: q(s, f"MERGE (n:{label} {{id: 1}}) SET n.name = 'alpha2'"),
        ran,
    )
    add(
        "String property on a node (non-`id` field)",
        CRITICAL,
        "symbol names, file paths, package names",
        lambda s: q(s, f"MATCH (n:{label} {{id: 1}}) RETURN n.name AS name"),
        lambda rows: rows and rows[0]["name"] == "alpha2",
    )

    # ---- batched ingest: UNWIND is the only composite-param door ------------
    add(
        "UNWIND batch CREATE, terminal",
        CRITICAL,
        "Stage A/B/C ingest throughput",
        lambda s: q(
            s,
            f"UNWIND $rows AS r CREATE (n:{label} {{id: r.id, name: r.name, v: r.v}})",
            rows=[{"id": i, "name": f"n{i}", "v": i} for i in range(2, 120)],
        ),
        ran,
    )
    add(
        "UNWIND batch MERGE by id + SET (upsert)",
        CRITICAL,
        "idempotent re-ingest without client-side dedup",
        lambda s: q(
            s,
            f"UNWIND $rows AS r MERGE (n:{label} {{id: r.id}}) SET n.v = r.v",
            rows=[{"id": i, "v": i * 2} for i in range(2, 60)],
        ),
        ran,
    )
    add(
        "UNWIND batch relationship CREATE with properties",
        CRITICAL,
        "every edge in the graph + the bitemporal quad",
        lambda s: q(
            s,
            f"""UNWIND $rows AS r
                MATCH (a:{label} {{id: r.src}})
                MATCH (b:{label} {{id: r.dst}})
                CREATE (a)-[:CALLS {{valid_from: r.vf, valid_to: r.vt,
                                     observed_at: r.oa, source: r.st,
                                     confidence: r.cf}}]->(b)""",
            rows=[
                {
                    "src": i,
                    "dst": i + 1,
                    "vf": 1000 + i,
                    "vt": 9_000_000,
                    "oa": 2000,
                    "st": "probe",
                    "cf": 1.0,
                }
                for i in range(2, 40)
            ],
        ),
        ran,
    )

    # ---- traversal: the core of Adit ---------------------------------------
    add(
        "Variable-length path -[:R*1..5]->",
        CRITICAL,
        "Q1 reachability + Q2 blast radius",
        lambda s: q(
            s,
            f"MATCH (a:{label} {{id: 2}})-[:CALLS*1..5]->(b) RETURN b.id AS id",
        ),
        truthy,
    )
    add(
        "Bind path to variable: MATCH p = ...",
        CRITICAL,
        "rendering the actual call path (the product)",
        lambda s: q(
            s,
            f"MATCH p = (a:{label} {{id: 2}})-[:CALLS*1..3]->(b) RETURN p",
        ),
        truthy,
    )
    add(
        "length(p) on a bound path",
        IMPORTANT,
        "path depth ranking in trace output",
        lambda s: q(
            s,
            f"MATCH p = (a:{label} {{id: 2}})-[:CALLS*1..3]->(b) RETURN length(p) AS d",
        ),
        lambda rows: rows and rows[0]["d"] is not None,
    )
    add(
        "nodes(p) destructuring",
        CRITICAL,
        "file:line path rendering - the demo money shot",
        lambda s: q(
            s,
            f"MATCH p = (a:{label} {{id: 2}})-[:CALLS*1..3]->(b) RETURN nodes(p) AS ns",
        ),
        lambda rows: rows and isinstance(rows[0]["ns"], list),
    )
    add(
        "Range predicate on relationship property",
        CRITICAL,
        "Q3 temporal window - the bitemporal model",
        lambda s: q(
            s,
            f"""MATCH (a:{label})-[e:CALLS]->(b)
                WHERE e.valid_from < 9000 AND e.valid_to > 0
                RETURN count(e) AS c""",
        ),
        lambda rows: rows and rows[0]["c"] >= 1,
    )
    add(
        "UNWIND as IN-substitute (batch id lookup)",
        CRITICAL,
        "47-CVE batch lookup without `WHERE x IN $ids`",
        lambda s: q(
            s,
            f"UNWIND $ids AS wanted MATCH (n:{label} {{id: wanted}}) RETURN n.id AS id",
            ids=[2, 3, 4],
        ),
        lambda rows: len(rows) == 3,
    )
    add(
        "UNWIND + variable-length path (batch traversal)",
        CRITICAL,
        "fan-out fallback if algo.MSpaths is unusable",
        lambda s: q(
            s,
            f"""UNWIND $srcs AS sv
                MATCH p = (a:{label} {{id: sv}})-[:CALLS*1..4]->(b)
                RETURN sv AS src, b.id AS dst""",
            srcs=[2, 3],
        ),
        truthy,
    )
    add(
        "Plain aggregation count()",
        CRITICAL,
        "Q2 affected-service counts",
        lambda s: q(s, f"MATCH (n:{label}) RETURN count(n) AS c"),
        lambda rows: rows and rows[0]["c"] > 0,
    )
    add(
        "DISTINCT in RETURN (not inside aggregate)",
        IMPORTANT,
        "dedup affected services",
        lambda s: q(s, f"MATCH (a:{label})-[:CALLS]->(b) RETURN DISTINCT b.id AS id"),
        truthy,
    )
    add(
        "collect()",
        OPTIONAL,
        "compact path assembly server-side",
        lambda s: q(s, f"MATCH (n:{label}) RETURN collect(n.id) AS ids"),
        truthy,
    )
    add(
        "ORDER BY + LIMIT",
        IMPORTANT,
        "ranking shortest paths first",
        lambda s: q(s, f"MATCH (n:{label}) RETURN n.id AS id ORDER BY n.id DESC LIMIT 3"),
        lambda rows: len(rows) == 3,
    )
    add(
        "OPTIONAL MATCH",
        IMPORTANT,
        "enrichment without dropping rows",
        lambda s: q(
            s,
            f"MATCH (n:{label} {{id: 2}}) OPTIONAL MATCH (n)-[:NOPE]->(x) RETURN n.id AS id",
        ),
        truthy,
    )
    add(
        "UNION",
        OPTIONAL,
        "combining install-time + runtime results",
        lambda s: q(
            s,
            f"MATCH (n:{label} {{id: 2}}) RETURN n.id AS id "
            f"UNION MATCH (n:{label} {{id: 3}}) RETURN n.id AS id",
        ),
        lambda rows: len(rows) == 2,
    )

    # ---- HydraDB native procedures -----------------------------------------
    # Composite params are UNWIND-only, so these must take INLINE literal lists.
    add(
        "algo.MSpaths with inline literal lists",
        CRITICAL,
        "THE sponsor-fit feature + headline benchmark",
        lambda s: q(
            s,
            f"""CALL algo.MSpaths({{
                  sourceLabel: '{label}', sourceProperty: 'id',
                  sourceValues: [2, 3], targetValues: [6, 7],
                  relTypes: ['CALLS'], relDirection: 'outgoing',
                  maxLen: 6, pathCount: 3, resultLimit: 100
                }}) YIELD path RETURN path""",
        ),
        truthy,
    )
    add(
        "algo.SPpaths with inline literal lists",
        OPTIONAL,
        "single-pair path fallback",
        lambda s: q(
            s,
            f"""CALL algo.SPpaths({{
                  sourceLabel: '{label}', sourceProperty: 'id',
                  sourceValues: [2], targetValues: [7],
                  relTypes: ['CALLS'], relDirection: 'outgoing',
                  maxLen: 10, resultLimit: 10
                }}) YIELD path RETURN path""",
        ),
        truthy,
    )

    # ---- indexing: legacy syntax -------------------------------------------
    add(
        "CREATE INDEX ON :Label(prop)  [legacy form]",
        IMPORTANT,
        "lookup speed on Symbol.id at scale",
        lambda s: q(s, f"CREATE INDEX ON :{label}(v)"),
        ran,
    )

    return p


def main() -> int:
    uri = sys.argv[1] if len(sys.argv) > 1 else "bolt://127.0.0.1:7687"
    token = sys.argv[2] if len(sys.argv) > 2 else "local-development-token-32-bytes"
    label = f"{L}{int(time.time()) % 100000}"

    print(f"probing {uri}   (label {label})\n")
    try:
        driver = GraphDatabase.driver(uri, auth=("neo4j", token))
        driver.verify_connectivity()
    except Exception as exc:  # noqa: BLE001
        print(f"CONNECT FAILED: {type(exc).__name__}: {exc}")
        return 2
    print("connected over Bolt\n")

    results: list[Result] = []
    with driver.session() as session:
        for probe in build_probes(label):
            started = time.perf_counter()
            try:
                rows = probe.run(session)
                ok = bool(probe.verify(rows))
                detail = "" if ok else f"unexpected result: {rows[:2]}"
            except Exception as exc:  # noqa: BLE001
                ok = False
                msg = str(exc).replace("\n", " ")
                detail = f"{type(exc).__name__}: {msg[:200]}"
            results.append(
                Result(
                    probe.name,
                    probe.tier,
                    probe.impact,
                    ok,
                    detail,
                    (time.perf_counter() - started) * 1000,
                )
            )
    driver.close()

    width = max(len(r.name) for r in results) + 2
    print(f"{'CAPABILITY'.ljust(width)}{'':6}{'ms':>7}  IMPACT IF BROKEN")
    print("-" * (width + 62))
    for r in results:
        mark = "PASS" if r.ok else "FAIL"
        print(f"{r.name.ljust(width)}{mark:6}{r.millis:7.1f}  {r.impact}")
        if not r.ok:
            print(f"{' ' * width}      -> {r.detail}")

    failed_critical = [r for r in results if not r.ok and r.tier == CRITICAL]
    failed_other = [r for r in results if not r.ok and r.tier != CRITICAL]

    print(f"\n{sum(r.ok for r in results)}/{len(results)} passed")
    if failed_critical:
        print(f"\n{len(failed_critical)} CRITICAL failure(s) - architecture must change:")
        for r in failed_critical:
            print(f"  - {r.name}  ({r.impact})")
    if failed_other:
        print(f"\n{len(failed_other)} non-critical failure(s) - workarounds needed:")
        for r in failed_other:
            print(f"  - {r.name}  ({r.impact})")
    return 1 if failed_critical else 0


if __name__ == "__main__":
    raise SystemExit(main())
