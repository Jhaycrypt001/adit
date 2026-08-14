"""Pass 1 + pass 2 against a fixture exercising the constructs that break naive tools.

These run without HydraDB -- extraction and resolution are pure. The fixture is
small but every file is there for a reason:

    orders.ts    -> imports through a BARREL, never names normalize.ts
    lib/index.ts -> `export *` plus an ALIASED re-export (padLeft -> pad)
    normalize.ts -> the only path to an EXTERNAL package (lodash)
    order.ts     -> `this.method()` chains inside a class
    ns.ts        -> NAMESPACE import, called as helpers.pad()
    orphan.ts    -> unreachable, and calls something that does not exist

A tool that reports `handleOrder -> merge` without following the barrel is
guessing. A tool that reports `orphan -> unknownGlobalThing` as bound is lying.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from adit.ingest.project import analyse, split_package

FIXTURE = Path(__file__).parent / "fixtures" / "tsapp"


@pytest.fixture(scope="module")
def graph():
    return analyse(FIXTURE)


def calls_from(graph, module: str, symbol: str) -> set[tuple[str, str]]:
    return {
        (cm, cs)
        for (m, s, cm, cs) in graph.internal_calls
        if m == module and s == symbol
    }


# -- project metadata -------------------------------------------------------


def test_reads_package_identity(graph):
    assert graph.package_name == "tsapp-fixture"
    assert graph.package_version == "1.2.3"


def test_all_fixture_modules_parsed(graph):
    assert "src/api/orders.ts" in graph.modules
    assert "src/lib/normalize.ts" in graph.modules
    assert graph.parse_errors == 0, "fixture must parse cleanly"


# -- symbol extraction ------------------------------------------------------


def test_extracts_functions_and_marks_exports(graph):
    mod = graph.modules["src/lib/normalize.ts"]
    assert "normalizePayload" in mod.symbols
    assert mod.symbols["normalizePayload"].exported
    assert mod.symbols["normalizePayload"].kind == "function"


def test_extracts_class_methods_qualified_by_class(graph):
    mod = graph.modules["src/services/order.ts"]
    assert "OrderService.handle" in mod.symbols
    assert "OrderService.validate" in mod.symbols
    assert mod.symbols["OrderService.handle"].kind == "method"


# -- the barrel file: the case that matters ---------------------------------


def test_call_resolves_through_barrel_reexport(graph):
    """orders.ts imports from '../lib', which never names normalize.ts."""
    targets = calls_from(graph, "src/api/orders.ts", "handleOrder")
    assert ("src/lib/normalize.ts", "normalizePayload") in targets, targets


def test_aliased_reexport_maps_back_to_declaration(graph):
    """The barrel exports padLeft as pad; resolution must undo the alias."""
    from adit.ingest.project import Resolver

    r = Resolver(graph.modules, FIXTURE)
    assert r.resolve_export("src/lib/index.ts", "pad") == ("src/lib/format.ts", "padLeft")


def test_star_reexport_resolves_names_it_never_mentions(graph):
    from adit.ingest.project import Resolver

    r = Resolver(graph.modules, FIXTURE)
    hit = r.resolve_export("src/lib/index.ts", "normalizePayload")
    assert hit == ("src/lib/normalize.ts", "normalizePayload")


def test_unknown_export_is_not_invented(graph):
    from adit.ingest.project import Resolver

    r = Resolver(graph.modules, FIXTURE)
    assert r.resolve_export("src/lib/index.ts", "noSuchThing") is None


# -- external package boundary ---------------------------------------------


def test_external_call_is_recorded_not_bound(graph):
    """lodash.merge cannot be bound until the version and its source are known."""
    refs = [r for r in graph.external_refs if r.package == "lodash"]
    assert refs, "lodash call was not recorded"
    ref = refs[0]
    assert ref.module == "src/lib/normalize.ts"
    assert ref.caller == "normalizePayload"
    assert ref.imported == "merge"
    assert ref.line > 0


def test_external_refs_do_not_leak_into_internal_calls(graph):
    assert all(cm in graph.modules for (_, _, cm, _) in graph.internal_calls)


@pytest.mark.parametrize(
    ("specifier", "expected"),
    [
        ("lodash", ("lodash", "")),
        ("lodash/merge", ("lodash", "merge")),
        ("@scope/pkg", ("@scope/pkg", "")),
        ("@scope/pkg/deep/path", ("@scope/pkg", "deep/path")),
    ],
)
def test_scoped_package_splitting(specifier, expected):
    assert split_package(specifier) == expected


# -- intra-class and namespace binding --------------------------------------


def test_this_method_binds_within_the_class(graph):
    targets = calls_from(graph, "src/services/order.ts", "OrderService.handle")
    assert ("src/services/order.ts", "OrderService.validate") in targets


def test_this_method_chains(graph):
    targets = calls_from(graph, "src/services/order.ts", "OrderService.validate")
    assert ("src/services/order.ts", "OrderService.audit") in targets


def test_namespace_import_member_call_resolves(graph):
    targets = calls_from(graph, "src/utils/ns.ts", "useNamespace")
    assert ("src/utils/helpers.ts", "pad") in targets, targets


# -- honesty ----------------------------------------------------------------


def test_unknown_global_is_counted_unresolved_not_guessed(graph):
    targets = calls_from(graph, "src/orphan.ts", "orphan")
    assert targets == set(), "a call to a nonexistent symbol must not bind"
    assert graph.unresolved_calls >= 1


def test_bind_rate_is_reported(graph):
    assert 0.0 < graph.bind_rate <= 1.0
    assert "bound" in graph.summary()


def test_node_modules_is_never_walked(graph):
    assert not any("node_modules" in m for m in graph.modules)
