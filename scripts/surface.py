"""Reverse-engineer HydraDB's actual executable Cypher surface.

Two rounds of shape-guessing produced 21/23 and 22/23 failures, but the engine's
error text is unusually precise -- it names the supported form rather than just
rejecting. So we stop guessing and map the surface empirically: start from the
single form the upstream README proves works, then vary exactly one dimension at
a time and record what survives.

Output is a spec, not a score. Every PASS line is a statement Adit is allowed to
emit; every FAIL line carries the engine's own description of what it wanted.

    py scripts/surface.py [bolt://127.0.0.1:7687] [token]
"""

from __future__ import annotations

import re
import sys
import time
from typing import Any

from neo4j import GraphDatabase

# The one form upstream documents as working:
#   CREATE (a {id: 1})-[:FOLLOWS]->(b {id: 2})
#   MATCH (a {id: 1})-[:FOLLOWS]->(b) RETURN b.id AS id

SECTIONS: list[tuple[str, list[tuple[str, str, dict[str, Any]]]]] = [
    (
        "A. CREATE forms",
        [
            ("README baseline: one-hop, no labels", "CREATE (a {id: 101})-[:R]->(b {id: 102})", {}),
            ("one-hop WITH labels", "CREATE (a:Sym {id: 111})-[:R]->(b:Sym {id: 112})", {}),
            ("standalone node, no label", "CREATE (a {id: 121})", {}),
            ("standalone node, with label", "CREATE (a:Sym {id: 131})", {}),
            ("one-hop + string property on nodes",
             "CREATE (a {id: 141, name: 'alpha'})-[:R]->(b {id: 142, name: 'beta'})", {}),
            ("one-hop + PROPERTIES ON THE EDGE",
             "CREATE (a {id: 151})-[:R {valid_from: 10, source: 'probe'}]->(b {id: 152})", {}),
            ("two-hop chain", "CREATE (a {id: 161})-[:R]->(b {id: 162})-[:R]->(c {id: 163})", {}),
            ("CREATE followed by RETURN", "CREATE (a {id: 171})-[:R]->(b {id: 172}) RETURN a.id AS id", {}),
            ("MATCH then CREATE edge between existing",
             "MATCH (a {id: 101}) MATCH (b {id: 102}) CREATE (a)-[:R2]->(b)", {}),
        ],
    ),
    (
        "B. MATCH / WHERE forms",
        [
            ("match by id, return property", "MATCH (a {id: 101})-[:R]->(b) RETURN b.id AS id", {}),
            ("match with label", "MATCH (a:Sym {id: 111})-[:R]->(b) RETURN b.id AS id", {}),
            ("single node match", "MATCH (a {id: 101}) RETURN a.id AS id", {}),
            ("return string property", "MATCH (a {id: 141})-[:R]->(b) RETURN b.name AS name", {}),
            ("WHERE on node integer property",
             "MATCH (a)-[:R]->(b) WHERE b.id > 100 RETURN b.id AS id", {}),
            ("WHERE on node string property",
             "MATCH (a)-[:R]->(b) WHERE b.name = 'beta' RETURN b.id AS id", {}),
            ("WHERE on EDGE property",
             "MATCH (a)-[e:R]->(b) WHERE e.valid_from > 5 RETURN b.id AS id", {}),
            ("return EDGE property", "MATCH (a)-[e:R]->(b) RETURN e.source AS src", {}),
            ("variable-length *1..3", "MATCH (a {id: 161})-[:R*1..3]->(b) RETURN b.id AS id", {}),
            ("variable-length *1..3 with label",
             "MATCH (a:Sym {id: 111})-[:R*1..3]->(b) RETURN b.id AS id", {}),
            ("bind path variable", "MATCH p = (a {id: 161})-[:R*1..3]->(b) RETURN b.id AS id", {}),
            ("reverse direction <-", "MATCH (a)<-[:R]-(b) RETURN a.id AS id", {}),
            ("undirected", "MATCH (a {id: 101})-[:R]-(b) RETURN b.id AS id", {}),
            ("two-hop fixed pattern",
             "MATCH (a {id: 161})-[:R]->(b)-[:R]->(c) RETURN c.id AS id", {}),
            ("OPTIONAL MATCH", "MATCH (a {id: 101}) OPTIONAL MATCH (a)-[:NOPE]->(x) RETURN a.id AS id", {}),
        ],
    ),
    (
        "C. RETURN / projection forms",
        [
            ("count(*)", "MATCH (a)-[:R]->(b) RETURN count(*) AS c", {}),
            ("count(binding)", "MATCH (a)-[:R]->(b) RETURN count(b) AS c", {}),
            ("two properties", "MATCH (a)-[:R]->(b) RETURN a.id AS src, b.id AS dst", {}),
            ("no alias", "MATCH (a {id: 101})-[:R]->(b) RETURN b.id", {}),
            ("DISTINCT", "MATCH (a)-[:R]->(b) RETURN DISTINCT b.id AS id", {}),
            ("ORDER BY", "MATCH (a)-[:R]->(b) RETURN b.id AS id ORDER BY b.id DESC", {}),
            ("LIMIT", "MATCH (a)-[:R]->(b) RETURN b.id AS id LIMIT 2", {}),
            ("ORDER BY + LIMIT", "MATCH (a)-[:R]->(b) RETURN b.id AS id ORDER BY b.id LIMIT 2", {}),
            ("SKIP + LIMIT", "MATCH (a)-[:R]->(b) RETURN b.id AS id SKIP 1 LIMIT 2", {}),
            ("collect()", "MATCH (a)-[:R]->(b) RETURN collect(b.id) AS ids", {}),
            ("min()", "MATCH (a)-[:R]->(b) RETURN min(b.id) AS lo", {}),
            ("return whole node", "MATCH (a {id: 101})-[:R]->(b) RETURN b", {}),
            ("UNION", "MATCH (a {id: 101})-[:R]->(b) RETURN b.id AS id "
                      "UNION MATCH (a {id: 111})-[:R]->(b) RETURN b.id AS id", {}),
        ],
    ),
    (
        "D. Parameters",
        [
            ("scalar int param", "MATCH (a {id: $v})-[:R]->(b) RETURN b.id AS id", {"v": 101}),
            ("scalar string param",
             "MATCH (a)-[:R]->(b) WHERE b.name = $n RETURN b.id AS id", {"n": "beta"}),
            ("UNWIND list-of-int param",
             "UNWIND $ids AS w MATCH (a {id: w})-[:R]->(b) RETURN b.id AS id",
             {"ids": [101, 111]}),
            ("UNWIND list-of-map: node upsert (MERGE id + SET)",
             "UNWIND $rows AS r MERGE (n {id: r.id}) SET n.name = r.name",
             {"rows": [{"id": 201 + i, "name": f"s{i}"} for i in range(5)]}),
            ("UNWIND list-of-map: node upsert + SET label",
             "UNWIND $rows AS r MERGE (n {id: r.id}) SET n:Sym, n.name = r.name",
             {"rows": [{"id": 211 + i, "name": f"t{i}"} for i in range(5)]}),
            ("UNWIND list-of-map: edge create one-hop, no edge props",
             "UNWIND $rows AS r MATCH (a {id: r.src}) MATCH (b {id: r.dst}) CREATE (a)-[:R3]->(b)",
             {"rows": [{"src": 201 + i, "dst": 202 + i} for i in range(4)]}),
            ("UNWIND list-of-map: edge create WITH edge props",
             "UNWIND $rows AS r MATCH (a {id: r.src}) MATCH (b {id: r.dst}) "
             "CREATE (a)-[:R4 {valid_from: r.vf}]->(b)",
             {"rows": [{"src": 201 + i, "dst": 202 + i, "vf": 10 + i} for i in range(4)]}),
            ("UNWIND + MERGE edge",
             "UNWIND $rows AS r MATCH (a {id: r.src}) MATCH (b {id: r.dst}) MERGE (a)-[:R5]->(b)",
             {"rows": [{"src": 201 + i, "dst": 202 + i} for i in range(4)]}),
        ],
    ),
    (
        "E. Native path procedures",
        [
            ("MSpaths, string sourceProperty (name)",
             "CALL algo.MSpaths({sourceLabel: 'Sym', sourceProperty: 'name', "
             "sourceValues: ['t0','t1'], targetValues: ['t3','t4'], relTypes: ['R3'], "
             "relDirection: 'outgoing', maxLen: 6, pathCount: 3, resultLimit: 100}) "
             "YIELD path RETURN path", {}),
            ("MSpaths, pairwise",
             "CALL algo.MSpaths({sourceLabel: 'Sym', sourceProperty: 'name', "
             "sourceValues: ['t0','t1','t2'], targetValues: ['t0','t1','t2'], pairwise: true, "
             "relTypes: ['R3'], relDirection: 'both', maxLen: 3, pathCount: 5, "
             "resultLimit: 100}) YIELD path RETURN path", {}),
            ("SPpaths with $sourceNode param",
             "CALL algo.SPpaths({sourceNode: $sourceNode, targetNode: $targetNode, "
             "relTypes: ['R3'], relDirection: 'outgoing', maxLen: 10, resultLimit: 10}) "
             "YIELD path RETURN path", {"sourceNode": "t0", "targetNode": "t3"}),
        ],
    ),
    (
        "F. Schema / index",
        [
            ("CREATE INDEX ON :Label(prop)", "CREATE INDEX ON :Sym(name)", {}),
            ("CREATE INDEX FOR ... ON ...", "CREATE INDEX FOR (n:Sym) ON (n.name)", {}),
            ("SHOW INDEXES", "SHOW INDEXES", {}),
            ("CALL db.indexes()", "CALL db.indexes()", {}),
        ],
    ),
]


def tidy(exc: Exception) -> str:
    """Pull the engine's own 'what I wanted' sentence out of the error blob."""
    raw = str(exc).replace("\n", " ")
    m = re.search(r"\{message: (.*?)\} \{gql_status", raw)
    msg = m.group(1) if m else raw
    msg = msg.replace("OpenCypher query is not supported yet: ", "")
    msg = msg.replace("OpenCypher parse error: ", "parse: ")
    msg = msg.replace("ClientProtocol query is not supported yet: ", "")
    return msg[:150]


def main() -> int:
    uri = sys.argv[1] if len(sys.argv) > 1 else "bolt://127.0.0.1:7687"
    token = sys.argv[2] if len(sys.argv) > 2 else "local-development-token-32-bytes"

    driver = GraphDatabase.driver(uri, auth=("neo4j", token))
    driver.verify_connectivity()
    print(f"mapping executable Cypher surface on {uri}\n")

    supported: list[str] = []
    total = passed = 0

    with driver.session() as session:
        for section, cases in SECTIONS:
            print(f"\n{section}")
            print("-" * 100)
            for note, cypher, params in cases:
                total += 1
                started = time.perf_counter()
                try:
                    rows = list(session.run(cypher, **params))
                    ms = (time.perf_counter() - started) * 1000
                    passed += 1
                    supported.append(note)
                    print(f"  PASS  {note:<48} {ms:6.1f}ms  rows={len(rows)}")
                except Exception as exc:  # noqa: BLE001
                    ms = (time.perf_counter() - started) * 1000
                    print(f"  FAIL  {note:<48} {ms:6.1f}ms")
                    print(f"        -> {tidy(exc)}")

    driver.close()
    print(f"\n\n{passed}/{total} statements executable\n")
    print("EXECUTABLE FORMS (this is the spec Adit must be written against):")
    for s in supported:
        print(f"  + {s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
