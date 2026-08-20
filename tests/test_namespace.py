"""Request-scoped id namespacing -- the isolation mechanism a hosted,
multi-tenant API needs, since HydraDB itself rejects any graph database name
it wasn't started with (confirmed live: `session(database="x")` fails with
"unknown graph database"). Pure, offline -- no HydraDB needed to test hashing.
"""

from __future__ import annotations

import threading

from adit.graph.ids import (
    current_namespace,
    node_id,
    scan_scope,
    scoped_key,
    symbol_key,
)


def test_no_namespace_by_default():
    """The CLI and every existing test never call scan_scope() -- node_id()
    must keep behaving exactly as it always has for them."""
    assert current_namespace() is None


def test_same_key_same_namespace_is_idempotent():
    key = symbol_key("pkg", "1.0.0", "a.ts", "f")
    with scan_scope("scan-a"):
        assert node_id(key) == node_id(key)


def test_different_namespaces_isolate_the_identical_key():
    """The actual isolation property: two 'tenants' scanning the identical
    repo must not collide on identity."""
    key = symbol_key("pkg", "1.0.0", "a.ts", "f")
    with scan_scope("scan-a"):
        id_a = node_id(key)
    with scan_scope("scan-b"):
        id_b = node_id(key)
    assert id_a != id_b


def test_namespace_resets_after_the_block():
    key = symbol_key("pkg", "1.0.0", "a.ts", "f")
    unscoped = node_id(key)
    with scan_scope("scan-a"):
        assert node_id(key) != unscoped
    assert current_namespace() is None
    assert node_id(key) == unscoped


def test_namespace_resets_even_on_exception():
    with contextlib_suppress():
        with scan_scope("scan-a"):
            raise RuntimeError("boom")
    assert current_namespace() is None


def contextlib_suppress():
    import contextlib

    return contextlib.suppress(RuntimeError)


def test_no_ambiguous_concatenation_collision():
    """namespace='a' + key='b:c' must not equal namespace='a:b' + key='c' --
    the null-byte separator in node_id() exists specifically to prevent this."""
    with scan_scope("a"):
        id1 = node_id("b:c")
    with scan_scope("a:b"):
        id2 = node_id("c")
    assert id1 != id2


def test_isolation_holds_under_real_concurrency():
    """ContextVar, not a thread-local or a module global -- confirm it
    actually isolates across concurrently running threads, which is the
    concurrency shape FastAPI serves requests under."""
    results: dict[str, int] = {}
    key = symbol_key("pkg", "1.0.0", "a.ts", "f")

    def worker(name: str) -> None:
        with scan_scope(name):
            results[name] = node_id(key)

    threads = [threading.Thread(target=worker, args=(f"scan-{i}",)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(set(results.values())) == 8, "concurrent scans collided on identity"


# -- the traversal-matching property ----------------------------------------
#
# node_id() namespacing covers every query anchored on `{id: ...}`, which is
# all of them except one: algo.MSpaths needs a *string* property to match, so
# reachability() is the single query whose isolation does not come for free.


def test_scoped_key_differs_per_namespace():
    """The property MSpaths matches on must differ per scan, or a traversal
    started in one scan can walk into another's subgraph."""
    key = symbol_key("pkg", "1.0.0", "a.ts", "f")
    with scan_scope("scan-a"):
        a = scoped_key(key)
    with scan_scope("scan-b"):
        b = scoped_key(key)
    assert a != b
    assert a.endswith(key) and b.endswith(key), "canonical key must remain recoverable"


def test_scoped_key_is_the_bare_key_outside_any_scan():
    """The CLI never opens a scan scope, and its nodes must stay matchable by
    their plain canonical key exactly as before this property existed."""
    key = symbol_key("pkg", "1.0.0", "a.ts", "f")
    assert scoped_key(key) == key


def test_scoped_key_has_no_ambiguous_concatenation():
    """Same trap as node_id's null byte: 'a' + '|b|c' must not collide with
    'a|b' + 'c'. The separator cannot occur in any canonical key builder's
    output, which is what makes the split unambiguous."""
    with scan_scope("a"):
        one = scoped_key("b|c")
    with scan_scope("a|b"):
        two = scoped_key("c")
    assert one != two
