"""algo.MSpaths (one server-side call) vs client-side fan-out (N x M round trips).

This is the headline number for "why HydraDB": answering "which of my services
reach any of these advisories" the naive way is `len(entrypoints) *
len(targets)` separate queries. algo.MSpaths resolves the whole batch
server-side in one call. Both paths are measured against the identical graph so
the comparison is honest, not a strawman.

Fixture shape: N independent 3-hop chains (entrypoint -> mid -> leaf). A subset
of the leaves are queried as "targets", so most (entrypoint, target) pairs are
genuinely unreachable and the engine has to actually search, not just return
instantly on an empty index.

    py scripts/bench_traversal.py [n_chains] [n_targets]
"""

from __future__ import annotations

import sys
import time

from adit.graph import Edge, Hydra, Label, Node, Queries, Writer

RUN = int(time.time() * 1000)


def build_fixture(writer: Writer, n_chains: int, n_targets: int) -> tuple[list[str], list[str]]:
    """N independent 3-hop chains: entry_i -> mid_i -> leaf_i."""
    label = f"Bench{RUN}"
    entries, mids, leaves = [], [], []
    nodes: list[Node] = []
    for i in range(n_chains):
        e, m, leaf = f"bench:{RUN}:e{i}", f"bench:{RUN}:m{i}", f"bench:{RUN}:leaf{i}"
        entries.append(e)
        mids.append(m)
        leaves.append(leaf)
        nodes += [
            Node(key=e, label=Label.SYMBOL, props={"name": f"entry{i}", "kind": label}),
            Node(key=m, label=Label.SYMBOL, props={"name": f"mid{i}", "kind": label}),
            Node(key=leaf, label=Label.SYMBOL, props={"name": f"leaf{i}", "kind": label}),
        ]
    writer.upsert_nodes(nodes)
    writer.create_edges(Edge.CALLS, list(zip(entries, mids, strict=True)))
    writer.create_edges(Edge.CALLS, list(zip(mids, leaves, strict=True)))
    return entries, leaves[:n_targets]


def main() -> int:
    n_chains = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    n_targets = int(sys.argv[2]) if len(sys.argv) > 2 else 15

    with Hydra() as hydra:
        writer = Writer(hydra)
        print(f"building fixture: {n_chains} chains, {n_targets} of their leaves as targets ...")
        t0 = time.perf_counter()
        entries, targets = build_fixture(writer, n_chains, n_targets)
        print(f"  written in {time.perf_counter() - t0:.2f}s\n")

        q = Queries(hydra)
        total_pairs = len(entries) * len(targets)

        print(f"algo.MSpaths -- 1 server-side call resolving all {total_pairs} pairs")
        t0 = time.perf_counter()
        result = q.reachability(entries, targets, max_len=4, path_count=1,
                                 result_limit=n_chains * 2)
        ms_elapsed = time.perf_counter() - t0
        print(f"  found {len(result.paths)} reachable pair(s) in {ms_elapsed:.3f}s\n")

        print(f"client fan-out -- {total_pairs} individual round trips")
        t0 = time.perf_counter()
        found, trips = q.reachability_fanout(entries, targets, max_len=4)
        fanout_elapsed = time.perf_counter() - t0
        print(f"  found {found} reachable pair(s) in {trips} round trips, {fanout_elapsed:.3f}s\n")

        # A speed comparison is worthless if the two methods disagree on the
        # answer -- assert parity, not just print two numbers side by side.
        if found != len(result.paths):
            print(f"  MISMATCH: MSpaths found {len(result.paths)}, fan-out found {found}")
            return 1
        print(f"  correctness: both methods found the same {found} reachable pair(s)\n")

        speedup = fanout_elapsed / ms_elapsed if ms_elapsed > 0 else float("inf")
        print("=" * 60)
        print(f"  {total_pairs:,} pairs checked")
        print(f"  MSpaths:  {ms_elapsed:7.3f}s   (1 call)")
        print(f"  fan-out:  {fanout_elapsed:7.3f}s   ({trips:,} calls)")
        print(f"  speedup:  {speedup:.1f}x")
        print(f"\n  at 200 services x 47 advisories (9,400 pairs), fan-out alone "
              f"projects to ~{9400/total_pairs*fanout_elapsed:.0f}s")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
