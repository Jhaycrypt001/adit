"""S1 end to end: parse a repo, write it to HydraDB, traverse it.

This is the first test where the whole stack runs together -- tree-sitter
extraction, cross-file resolution, batched writes, and `algo.MSpaths` traversal
returning a renderable path.

The assertion that matters is the barrel one. `orders.ts` imports from `../lib`
and never mentions `normalize.ts`; only a resolver that follows `export *` can
connect `handleOrder` to `merge`. And `orphan` must stay unreachable, because a
tool that reports paths which do not exist is worse than no tool.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from adit.graph import Hydra, Queries
from adit.graph.ids import symbol_key
from adit.ingest.emit import emit, entrypoint_keys
from adit.ingest.project import analyse

pytestmark = pytest.mark.integration

FIXTURE = Path(__file__).parent / "fixtures" / "tsapp"


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
def ingested(hydra):
    """Ingest the fixture under a run-unique version.

    Node ids are hashes of keys, so a fixed version would make every run write
    into the same nodes and append duplicate CALLS edges. Namespacing by
    version keeps runs independent without needing a teardown.
    """
    graph = analyse(FIXTURE)
    graph.package_version = f"t{int(time.time() * 1000)}"
    emit(graph, hydra)
    return graph


def sym(graph, module: str, name: str) -> str:
    return symbol_key(graph.package_name, graph.package_version, module, name)


# -- the graph landed -------------------------------------------------------


def test_symbols_persisted_with_source_location(ingested, hydra):
    from adit.graph.ids import node_id

    key = sym(ingested, "src/lib/normalize.ts", "normalizePayload")
    rows = hydra.run(
        f"MATCH (n {{id: {node_id(key)}}}) RETURN n.name AS name, n.file AS file, n.line AS line"
    )
    assert rows, "symbol not written"
    assert rows[0]["name"] == "normalizePayload"
    assert rows[0]["file"] == "src/lib/normalize.ts"
    assert rows[0]["line"] > 0, "line number is what makes the path clickable"


def test_exported_symbols_are_entrypoints(ingested, hydra):
    from adit.graph.ids import node_id

    key = sym(ingested, "src/api/orders.ts", "handleOrder")
    rows = hydra.run(f"MATCH (n {{id: {node_id(key)}}}) RETURN n.entrypoint AS ep")
    assert rows and rows[0]["ep"] is True


# -- reachability through the barrel ---------------------------------------


def test_reachable_through_barrel_reexport(ingested, hydra):
    q = Queries(hydra)
    result = q.reachability(
        [sym(ingested, "src/api/orders.ts", "handleOrder")],
        [sym(ingested, "src/lib/normalize.ts", "normalizePayload")],
        max_len=6,
    )
    assert result.reachable, "barrel re-export broke the chain"
    path = result.shortest
    assert path is not None
    assert [n["name"] for n in path.nodes] == ["handleOrder", "normalizePayload"]
    # Every hop must carry a location, or the output is not verifiable by hand.
    assert all(n.get("file") and n.get("line") for n in path.nodes)


def test_class_method_chain_is_traversable(ingested, hydra):
    q = Queries(hydra)
    result = q.reachability(
        [sym(ingested, "src/services/order.ts", "OrderService.handle")],
        [sym(ingested, "src/services/order.ts", "OrderService.audit")],
        max_len=4,
    )
    assert result.reachable
    assert [n["name"] for n in result.shortest.nodes] == [
        "OrderService.handle",
        "OrderService.validate",
        "OrderService.audit",
    ]


def test_dispatch_reaches_service_through_import(ingested, hydra):
    q = Queries(hydra)
    result = q.reachability(
        [sym(ingested, "src/api/orders.ts", "dispatch")],
        [sym(ingested, "src/services/order.ts", "OrderService.audit")],
        max_len=8,
    )
    assert result.reachable, "cross-module class method chain not reachable"


# -- the negative case ------------------------------------------------------


def test_orphan_is_not_reachable(ingested, hydra):
    q = Queries(hydra)
    result = q.reachability(
        [sym(ingested, "src/orphan.ts", "orphan")],
        [sym(ingested, "src/lib/normalize.ts", "normalizePayload")],
        max_len=10,
    )
    assert not result.reachable
    assert result.paths == []
    assert "no path within 10 hops" in result.explain_absence()


def test_nothing_reaches_the_orphan(ingested, hydra):
    q = Queries(hydra)
    result = q.reachability(
        entrypoint_keys(ingested)[:40],
        [sym(ingested, "src/orphan.ts", "orphan")],
        max_len=10,
    )
    assert not result.reachable


# -- backward slice ---------------------------------------------------------


def test_backward_slice_finds_the_caller(ingested, hydra):
    """What breaks if normalizePayload changes? handleOrder does."""
    q = Queries(hydra)
    callers = q.callers_of(sym(ingested, "src/lib/normalize.ts", "normalizePayload"), max_len=6)
    assert sym(ingested, "src/api/orders.ts", "handleOrder") in callers


def test_unused_helper_has_no_callers(ingested, hydra):
    q = Queries(hydra)
    assert q.callers_of(sym(ingested, "src/lib/normalize.ts", "unusedHelper"), max_len=6) == []


# -- external boundary ------------------------------------------------------


def test_external_refs_returned_for_later_binding(ingested, hydra):
    _, refs = emit(ingested, hydra)
    lodash = [r for r in refs if r.package == "lodash"]
    assert lodash and lodash[0].imported == "merge"
