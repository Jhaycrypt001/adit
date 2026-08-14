"""Three questions that decide Adit's ingest and rendering design.

The surface map (scripts/surface.py) established WHAT executes. This establishes
what those statements MEAN, which the error messages cannot tell us:

  Q1. Does `CREATE (a {id: X})-[:R]->(b {id: Y})` attach to pre-existing nodes
      with those ids, or silently duplicate them? Batch edge writes are not
      supported, so this single form is the only way Adit can build edges -- if
      it duplicates, the whole ingest strategy changes.

  Q2. What does algo.MSpaths actually hand back in `path`? Adit's product is
      *showing the call path* file:line by file:line. RETURN cannot project
      nodes(p) or length(p), so if MSpaths' path payload is opaque we cannot
      render a path server-side at all and must reassemble client-side.

  Q3. How fast are single-edge CREATEs, and does wrapping them in one explicit
      transaction amortise the cost? Edges cannot be batched via UNWIND, so this
      number sets the ceiling on how large a repo Adit can ingest.

    py scripts/semantics.py [bolt://127.0.0.1:7687] [token]
"""

from __future__ import annotations

import sys
import time

from neo4j import GraphDatabase

BASE = 900_000  # id space for this probe, clear of the surface probe's


def q1_identity(session) -> None:
    print("\nQ1. Does CREATE attach to existing nodes, or duplicate?")
    print("-" * 78)

    a, b, c = BASE + 1, BASE + 2, BASE + 3

    session.run(f"CREATE (x {{id: {a}, name: 'q1a'}})-[:E1]->(y {{id: {b}, name: 'q1b'}})")
    # Reference the SAME ids again with a different edge type.
    session.run(f"CREATE (x {{id: {a}}})-[:E2]->(y {{id: {c}, name: 'q1c'}})")

    rows = list(session.run(f"MATCH (n {{id: {a}}}) RETURN n.name AS name"))
    print(f"  nodes matching id={a}: {len(rows)}  -> {[r['name'] for r in rows]}")

    out = list(session.run(f"MATCH (x {{id: {a}}})-[:E1]->(y) RETURN y.id AS id"))
    out2 = list(session.run(f"MATCH (x {{id: {a}}})-[:E2]->(y) RETURN y.id AS id"))
    print(f"  id={a} -[:E1]-> {[r['id'] for r in out]}")
    print(f"  id={a} -[:E2]-> {[r['id'] for r in out2]}")

    if len(rows) == 1 and out and out2:
        print("  VERDICT: CREATE attaches by id. Nodes are upserted, edges appended.")
        print("           -> ingest can emit edges directly; no pre-pass needed.")
    elif len(rows) > 1:
        print("  VERDICT: CREATE DUPLICATES nodes. Must pre-create nodes via UNWIND")
        print("           upsert, and edges must reference them some other way.")
    else:
        print("  VERDICT: unclear -- inspect above.")

    # Does the second CREATE clobber properties set by the first?
    nm = list(session.run(f"MATCH (n {{id: {a}}}) RETURN n.name AS name"))
    print(f"  property after re-CREATE without name: {[r['name'] for r in nm]}")


def q2_mspaths(session) -> None:
    print("\nQ2. What does algo.MSpaths return in `path`?")
    print("-" * 78)

    # Build a known 4-hop chain: p0 -> p1 -> p2 -> p3 -> p4
    ids = [BASE + 10 + i for i in range(5)]
    for i in range(4):
        session.run(
            f"CREATE (a:QSym {{id: {ids[i]}, name: 'p{i}'}})"
            f"-[:CALLS {{valid_from: {100 + i}, valid_to: 9000000, source: 'probe'}}]->"
            f"(b:QSym {{id: {ids[i+1]}, name: 'p{i+1}'}})"
        )

    # Variable-length MATCH requires a fixed *integer id* as the anchor -- a
    # property match like {name: 'p0'} is rejected. Adit therefore resolves
    # names to ids client-side, then traverses from the id.
    hop = list(
        session.run(f"MATCH (a:QSym {{id: {ids[0]}}})-[:CALLS*1..4]->(b) RETURN b.name AS name")
    )
    print(f"  var-length reachability p0 -> {sorted(str(r['name']) for r in hop)}")

    try:
        rows = list(
            session.run(
                "CALL algo.MSpaths({sourceLabel: 'QSym', sourceProperty: 'name', "
                "sourceValues: ['p0'], targetValues: ['p4'], relTypes: ['CALLS'], "
                "relDirection: 'outgoing', maxLen: 8, pathCount: 3, resultLimit: 50}) "
                "YIELD path RETURN path"
            )
        )
        print(f"  MSpaths rows: {len(rows)}")
        for r in rows[:2]:
            path = r["path"]
            print(f"  python type : {type(path).__name__}")
            print(f"  repr        : {repr(path)[:300]}")
            for attr in ("nodes", "relationships", "start_node", "end_node"):
                if hasattr(path, attr):
                    val = getattr(path, attr)
                    print(f"  .{attr:<14}: {str(val)[:200]}")
            if hasattr(path, "nodes"):
                try:
                    names = [dict(n).get("name") for n in path.nodes]
                    print(f"  RENDERABLE  : {' -> '.join(str(n) for n in names)}")
                except Exception as exc:  # noqa: BLE001
                    print(f"  node deref failed: {exc}")
    except Exception as exc:  # noqa: BLE001
        print(f"  MSpaths FAILED: {str(exc)[:200]}")

    # Can we get an ordered path out of plain Cypher instead?
    for note, cypher in [
        ("reachable p0->p4 (anchored on id)",
         f"MATCH (a:QSym {{id: {ids[0]}}})-[:CALLS*1..8]->(b:QSym {{id: {ids[4]}}}) "
         f"RETURN b.name AS name"),
        ("temporal filter on edge inside var-length",
         f"MATCH (a:QSym {{id: {ids[0]}}})-[e:CALLS*1..8]->(b) "
         f"WHERE e.valid_from > 0 RETURN b.name AS name"),
        ("NEGATIVE: unreachable target returns empty",
         f"MATCH (a:QSym {{id: {ids[4]}}})-[:CALLS*1..8]->(b:QSym {{id: {ids[0]}}}) "
         f"RETURN b.name AS name"),
    ]:
        try:
            rows = list(session.run(cypher))
            print(f"  {note}: rows={len(rows)} {[str(r['name']) for r in rows][:5]}")
        except Exception as exc:  # noqa: BLE001
            print(f"  {note}: FAILED {str(exc)[:140]}")


def q3_throughput(session, driver) -> None:
    print("\nQ3. Edge write throughput (edges cannot be UNWIND-batched)")
    print("-" * 78)

    n = 200

    start = time.perf_counter()
    for i in range(n):
        session.run(
            f"CREATE (a {{id: {BASE + 1000 + i}}})-[:T1 {{valid_from: {i}}}]->"
            f"(b {{id: {BASE + 1001 + i}}})"
        )
    seq = time.perf_counter() - start
    print(f"  autocommit, one statement per call : {n/seq:8.0f} edges/sec  ({seq:.2f}s)")

    start = time.perf_counter()
    with driver.session() as s2:
        tx = s2.begin_transaction()
        for i in range(n):
            tx.run(
                f"CREATE (a {{id: {BASE + 2000 + i}}})-[:T2 {{valid_from: {i}}}]->"
                f"(b {{id: {BASE + 2001 + i}}})"
            )
        tx.commit()
    txn = time.perf_counter() - start
    print(f"  single explicit transaction        : {n/txn:8.0f} edges/sec  ({txn:.2f}s)")

    start = time.perf_counter()
    session.run(
        "UNWIND $rows AS r MERGE (n {id: r.id}) SET n:Bulk, n.name = r.name",
        rows=[{"id": BASE + 3000 + i, "name": f"b{i}"} for i in range(2000)],
    )
    bulk = time.perf_counter() - start
    print(f"  UNWIND node upsert (2000 nodes)    : {2000/bulk:8.0f} nodes/sec ({bulk:.2f}s)")

    speedup = seq / txn if txn else 0
    print(f"\n  transaction batching speedup: {speedup:.1f}x")
    print(f"  projected time for 100k edges: {100_000/(n/txn)/60:.1f} min (txn-batched)")


def main() -> int:
    uri = sys.argv[1] if len(sys.argv) > 1 else "bolt://127.0.0.1:7687"
    token = sys.argv[2] if len(sys.argv) > 2 else "local-development-token-32-bytes"

    driver = GraphDatabase.driver(uri, auth=("neo4j", token))
    driver.verify_connectivity()

    with driver.session() as session:
        q1_identity(session)
        q2_mspaths(session)
        q3_throughput(session, driver)

    driver.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
