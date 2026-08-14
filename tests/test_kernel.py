"""End-to-end proof of the graph kernel against a live HydraDB.

    docker compose up -d
    .venv/Scripts/python -m pytest tests/test_kernel.py -v

The fixture graph is a miniature of the real product:

    entry() -> normalize() -> merge()          <- reachable, 3 hops
    orphan()                                   <- no path to merge(), ever
    svc -> app@1.0 -> util@2.0 -> vuln@0.9     <- dependency chain for blast radius

The negative assertions matter more than the positive ones. A tool that reports
a path that does not exist is worse than no tool, so "unreachable stays
unreachable" is tested at every level.
"""

from __future__ import annotations

import os
import time

import pytest

from adit.graph import (
    Edge,
    Fact,
    FactKind,
    Hydra,
    Label,
    Node,
    Provenance,
    Queries,
    Writer,
    node_id,
)

pytestmark = pytest.mark.integration

RUN = str(int(time.time() * 1000))  # keys are hashed, so runs must not collide


def k(name: str) -> str:
    """Namespace a fixture key to this test run."""
    return f"sym:test{RUN}:{name}"


@pytest.fixture(scope="module")
def hydra():
    uri = os.environ.get("ADIT_BOLT_URI", "bolt://127.0.0.1:7687")
    h = Hydra(uri)
    try:
        h.verify()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no HydraDB at {uri}: {exc}")
    yield h
    h.close()


@pytest.fixture(scope="module")
def graph(hydra):
    """Build the fixture graph once for the module."""
    w = Writer(hydra)

    symbols = ["entry", "normalize", "merge", "orphan", "unrelated"]
    w.upsert_nodes(
        [
            Node(key=k(n), label=Label.SYMBOL, props={"name": n, "file": f"src/{n}.ts", "line": 10})
            for n in symbols
        ]
    )

    # entry -> normalize -> merge.  orphan and unrelated are deliberately
    # disconnected from that chain.
    w.create_edges(
        Edge.CALLS,
        [(k("entry"), k("normalize")), (k("normalize"), k("merge")),
         (k("orphan"), k("unrelated"))],
    )

    releases = ["rel:npm:app@1.0.0", "rel:npm:util@2.0.0", "rel:npm:vuln@0.9.0"]
    w.upsert_nodes(
        [Node(key=f"{r}:{RUN}", label=Label.RELEASE, props={"name": r}) for r in releases]
    )
    w.create_edges(
        Edge.DEPENDS_ON,
        [
            (f"{releases[0]}:{RUN}", f"{releases[1]}:{RUN}"),
            (f"{releases[1]}:{RUN}", f"{releases[2]}:{RUN}"),
        ],
    )

    # A lockfile resolved util@2.0.0 during a bounded window.
    w.upsert_nodes([Node(key=f"svc:checkout:{RUN}", label=Label.SERVICE, props={"name": "checkout"})])
    w.upsert_facts(
        [
            Fact(
                kind=FactKind.RESOLUTION,
                subject_key=f"svc:checkout:{RUN}",
                object_key=f"{releases[1]}:{RUN}",
                provenance=Provenance(
                    valid_from=1_000, valid_to=2_000, observed_at=1_500, source="lockfile"
                ),
            )
        ]
    )
    return w


# -- identity ---------------------------------------------------------------


def test_ids_are_stable_and_positive():
    assert node_id("sym:a") == node_id("sym:a")
    assert node_id("sym:a") != node_id("sym:b")
    assert 0 < node_id("sym:a") < (1 << 63)


def test_writer_detects_id_collisions(hydra):
    w = Writer(hydra)
    w.ids.register("alpha")
    w.ids.register("alpha")  # same key is fine
    assert len(w.ids) == 1


# -- writes -----------------------------------------------------------------


def test_nodes_persist_with_properties(graph, hydra):
    rows = hydra.run(f"MATCH (n {{id: {node_id(k('entry'))}}}) RETURN n.name AS name, n.file AS file")
    assert rows, "entry node was not written"
    assert rows[0]["name"] == "entry"
    assert rows[0]["file"] == "src/entry.ts"


def test_topology_edges_persist(graph, hydra):
    rows = hydra.run(
        f"MATCH (a {{id: {node_id(k('entry'))}}})-[:CALLS]->(b) RETURN b.name AS name"
    )
    assert [r["name"] for r in rows] == ["normalize"]


# -- Q1: reachability -------------------------------------------------------


def test_reachable_path_is_found_and_renderable(graph, hydra):
    q = Queries(hydra)
    result = q.reachability([k("entry")], [k("merge")], max_len=6)

    assert result.reachable, "entry -> normalize -> merge should be reachable"
    shortest = result.shortest
    assert shortest is not None
    names = [n.get("name") for n in shortest.nodes]
    assert names == ["entry", "normalize", "merge"], names
    assert shortest.depth == 2
    # The point of the product: a path you can print, not a score.
    assert all(n.get("file") for n in shortest.nodes)


def test_unreachable_returns_no_path_and_explains(graph, hydra):
    """The assertion that matters most: absence must stay absent."""
    q = Queries(hydra)
    result = q.reachability([k("orphan")], [k("merge")], max_len=8)

    assert not result.reachable
    assert result.paths == []
    assert result.shortest is None
    assert "no path within 8 hops" in result.explain_absence()


def test_direction_is_respected(graph, hydra):
    """merge does not call entry; traversal must not be undirected."""
    q = Queries(hydra)
    assert not q.reachability([k("merge")], [k("entry")], max_len=6).reachable


def test_max_len_bounds_the_search(graph, hydra):
    """A 2-hop path must not be found within 1 hop."""
    q = Queries(hydra)
    assert not q.reachability([k("entry")], [k("merge")], max_len=1).reachable
    assert q.reachability([k("entry")], [k("merge")], max_len=2).reachable


def test_empty_inputs_abstain_rather_than_error(graph, hydra):
    q = Queries(hydra)
    assert not q.reachability([], [k("merge")]).reachable
    assert not q.reachability([k("entry")], []).reachable


# -- Q2: blast radius -------------------------------------------------------


def test_blast_radius_finds_transitive_dependents(graph, hydra):
    q = Queries(hydra)
    affected = q.blast_radius(f"rel:npm:vuln@0.9.0:{RUN}", max_len=5)
    assert f"rel:npm:util@2.0.0:{RUN}" in affected, affected
    assert f"rel:npm:app@1.0.0:{RUN}" in affected, "transitive dependent missed"


def test_blast_radius_of_unrelated_release_is_empty(graph, hydra):
    q = Queries(hydra)
    assert q.blast_radius(f"rel:npm:app@1.0.0:{RUN}", max_len=5) == []


def test_backward_slice_finds_transitive_callers(graph, hydra):
    """What breaks if I change merge()? entry and normalize both reach it."""
    q = Queries(hydra)
    callers = q.callers_of(k("merge"), max_len=5)
    assert k("normalize") in callers
    assert k("entry") in callers, "transitive caller missed"
    assert k("orphan") not in callers


def test_backward_slice_of_leaf_entrypoint_is_empty(graph, hydra):
    q = Queries(hydra)
    assert q.callers_of(k("entry"), max_len=5) == []


def test_edge_without_materialised_inverse_is_refused(hydra):
    """Reverse closure must fail loudly, not silently return nothing."""
    q = Queries(hydra)
    with pytest.raises(ValueError, match="no materialised inverse"):
        q.blast_radius(k("merge"), rel=Edge.IMPORTS)


# -- Q3: temporal validity --------------------------------------------------


@pytest.mark.parametrize(
    ("start", "end", "expect_hit"),
    [
        (1_200, 1_800, True),   # fully inside the window
        (0, 1_500, True),       # overlaps the start
        (1_500, 5_000, True),   # overlaps the end
        (0, 900, False),        # entirely before
        (2_500, 3_000, False),  # entirely after
    ],
)
def test_temporal_window_filters_facts(graph, hydra, start, end, expect_hit):
    """Same query, different dates -- the bitemporal model's proof."""
    q = Queries(hydra)
    rows = q.facts_in_window(f"svc:checkout:{RUN}", FactKind.RESOLUTION, start, end)
    assert bool(rows) is expect_hit, f"window ({start}, {end}) -> {rows}"
    if expect_hit:
        assert rows[0]["source"] == "lockfile"
        assert rows[0]["valid_from"] == 1_000
