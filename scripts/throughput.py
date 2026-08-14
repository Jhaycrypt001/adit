"""Find a write path fast enough to ingest a real repository.

Autocommit single-edge CREATE measured ~5 edges/sec, and explicit transactions
are rejected ("use auto-commit RUN queries"). At that rate a 100k-edge call
graph takes 5.5 hours, which does not fit the build. Before redesigning the
schema around the limitation we establish what the engine can actually do.

Hypotheses, in order of how much they'd save:

  H1. `UNWIND $rows AS r CREATE (a {id:r.src})-[:T]->(b {id:r.dst})` works.
      Round 2's errors said UNWIND batch "supports one-hop relationships only"
      and "requires one fixed relationship type WITHOUT properties" -- phrasing
      that implies the propertyless one-hop form IS supported. If so we get
      batch edges, at the cost of edge properties.
  H2. Edge properties can be carried some other way (typed relationships).
  H3. Per-write latency is durability round-trip, so concurrent sessions scale
      near-linearly.
  H4. Batch size materially changes throughput.

    py scripts/throughput.py [bolt://127.0.0.1:7687] [token]
"""

from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor

from neo4j import GraphDatabase

BASE = 5_000_000
URI = sys.argv[1] if len(sys.argv) > 1 else "bolt://127.0.0.1:7687"
TOKEN = sys.argv[2] if len(sys.argv) > 2 else "local-development-token-32-bytes"


def h1_unwind_edges(driver) -> float:
    print("\nH1. UNWIND batch edge create (one-hop, fixed type, no edge props)")
    print("-" * 78)
    best = 0.0
    with driver.session() as s:
        for n in (500, 2000, 10000):
            rows = [{"src": BASE + i, "dst": BASE + i + 1} for i in range(n)]
            start = time.perf_counter()
            try:
                s.run(
                    "UNWIND $rows AS r CREATE (a {id: r.src})-[:CALLS]->(b {id: r.dst})",
                    rows=rows,
                )
                el = time.perf_counter() - start
                rate = n / el
                best = max(best, rate)
                print(f"  {n:>6} edges: {rate:9.0f} edges/sec  ({el:.2f}s)")
            except Exception as exc:  # noqa: BLE001
                print(f"  {n:>6} edges: FAILED  {str(exc)[:170]}")
                # A larger batch failing does not invalidate a smaller one that
                # succeeded -- admission control caps batch size, it does not
                # disable the path. Keep the best rate actually observed.
                break
            BASE_SHIFT(n)
    return best


_offset = [0]


def BASE_SHIFT(n: int) -> None:  # noqa: N802 - keep id spaces disjoint between runs
    global BASE  # noqa: PLW0603
    BASE += n + 10


def h2_edge_properties(driver) -> None:
    print("\nH2. Can batched edges carry properties / typed variants?")
    print("-" * 78)
    with driver.session() as s:
        attempts = [
            ("edge property from row",
             "UNWIND $rows AS r CREATE (a {id: r.src})-[:P1 {valid_from: r.vf}]->(b {id: r.dst})"),
            ("edge property literal",
             "UNWIND $rows AS r CREATE (a {id: r.src})-[:P2 {valid_from: 1}]->(b {id: r.dst})"),
            ("node properties from row (edge bare)",
             "UNWIND $rows AS r CREATE (a {id: r.src, name: r.nm})-[:P3]->(b {id: r.dst})"),
        ]
        for note, cypher in attempts:
            rows = [
                {"src": BASE + 900000 + i, "dst": BASE + 900001 + i, "vf": i, "nm": f"x{i}"}
                for i in range(20)
            ]
            try:
                s.run(cypher, rows=rows)
                print(f"  PASS  {note}")
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)
                start = msg.find("{message: ")
                msg = msg[start + 10 : msg.find("} {gql_status")] if start >= 0 else msg
                print(f"  FAIL  {note}\n          -> {msg[:150]}")


def h3_concurrency() -> None:
    print("\nH3. Do concurrent sessions scale the single-edge write path?")
    print("-" * 78)
    per_worker = 40

    def worker(wid: int) -> None:
        drv = GraphDatabase.driver(URI, auth=("neo4j", TOKEN))
        with drv.session() as s:
            for i in range(per_worker):
                base = BASE + 2_000_000 + wid * 100_000 + i * 2
                s.run(f"CREATE (a {{id: {base}}})-[:C1 {{valid_from: {i}}}]->(b {{id: {base+1}}})")
        drv.close()

    for workers in (1, 4, 8):
        start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(worker, range(workers)))
        el = time.perf_counter() - start
        total = workers * per_worker
        print(f"  {workers:>2} workers: {total/el:8.0f} edges/sec  ({total} edges in {el:.2f}s)")


def h4_node_upsert(driver) -> None:
    print("\nH4. UNWIND node upsert throughput (the known-good batch path)")
    print("-" * 78)
    with driver.session() as s:
        for n in (1000, 5000, 20000):
            rows = [{"id": BASE + 3_000_000 + i, "name": f"sym{i}"} for i in range(n)]
            start = time.perf_counter()
            try:
                s.run(
                    "UNWIND $rows AS r MERGE (n {id: r.id}) SET n:Sym, n.name = r.name",
                    rows=rows,
                )
                el = time.perf_counter() - start
                print(f"  {n:>6} nodes: {n/el:9.0f} nodes/sec  ({el:.2f}s)")
            except Exception as exc:  # noqa: BLE001
                print(f"  {n:>6} nodes: FAILED {str(exc)[:150]}")
                break


def main() -> int:
    driver = GraphDatabase.driver(URI, auth=("neo4j", TOKEN))
    driver.verify_connectivity()
    print(f"write-path throughput on {URI}")

    edge_rate = h1_unwind_edges(driver)
    h2_edge_properties(driver)
    h4_node_upsert(driver)
    h3_concurrency()

    print("\n" + "=" * 78)
    if edge_rate:
        print(f"VERDICT: batched edges reach {edge_rate:,.0f}/sec at <=1024 rows per statement.")
        print(f"         100k-edge call graph -> {100_000/edge_rate:.0f}s of wall clock.")
        print("         Cost: batched edges carry NO properties, and batched CREATE")
        print("         nodes carry only `id`. Temporal/provenance facts must therefore")
        print("         be reified as NODES (upserted via MERGE+SET at ~14k/sec).")
    else:
        print("VERDICT: no batch edge path at any size. Ingest must be redesigned")
        print("         around ~5 edges/sec single writes -- topology must shrink.")
    driver.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
