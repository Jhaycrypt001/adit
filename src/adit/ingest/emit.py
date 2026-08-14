"""Write a resolved ProjectGraph into HydraDB.

Everything here rides the two fast batched paths measured in
scripts/throughput.py -- node upsert at ~14,500/sec and bare edges at
~10,000/sec -- so a large repository lands in seconds rather than hours.

External refs are deliberately *not* emitted as CALLS edges. A call to
`lodash.merge` has no target node until the lockfile supplies the version
(stage B) and the package's own source supplies the symbol (stage D). Inventing
a placeholder node now would mean rewriting node identity later, and identity is
a hash of the key. They are returned for those stages to consume.
"""

from __future__ import annotations

import logging

from ..graph import Edge, Hydra, Label, Node, Writer
from ..graph.ids import module_key, package_key, symbol_key
from .project import MODULE_SCOPE, ExternalRef, ProjectGraph

log = logging.getLogger(__name__)


def emit(graph: ProjectGraph, hydra: Hydra) -> tuple[Writer, list[ExternalRef]]:
    """Persist the code graph. Returns the writer (for stats) and external refs."""
    w = Writer(hydra)
    pkg, ver = graph.package_name, graph.package_version

    def sym(module: str, name: str) -> str:
        return symbol_key(pkg, ver, module, name)

    # -- nodes -------------------------------------------------------------
    modules = [
        Node(
            key=module_key(pkg, ver, path),
            label=Label.MODULE,
            props={"path": path, "package": pkg, "version": ver},
        )
        for path in graph.modules
    ]

    symbols: list[Node] = []
    for path, info in graph.modules.items():
        for s in info.symbols.values():
            symbols.append(
                Node(
                    key=sym(path, s.name),
                    label=Label.SYMBOL,
                    props={
                        "name": s.name,
                        "kind": s.kind,
                        "file": path,
                        "line": s.line,
                        "package": pkg,
                        "version": ver,
                        "exported": s.exported,
                        # Reachability needs roots. An exported symbol is
                        # callable from outside the package; module-scope code
                        # runs on import. Both are genuine entrypoints, and a
                        # graph without roots answers nothing.
                        "entrypoint": s.exported or s.name == MODULE_SCOPE,
                        # Test-only reachability is real but triaged differently
                        # by real teams, so it is labelled rather than dropped.
                        "is_test": _looks_like_test(path),
                    },
                )
            )

    packages = [
        Node(key=package_key("npm", name), label=Label.PACKAGE,
             props={"name": name, "ecosystem": "npm"})
        for name in {p for _, p in graph.package_imports}
    ]

    w.upsert_nodes(modules)
    w.upsert_nodes(symbols)
    w.upsert_nodes(packages)

    # -- edges -------------------------------------------------------------
    w.create_edges(
        Edge.DEFINES,
        [
            (module_key(pkg, ver, path), sym(path, s.name))
            for path, info in graph.modules.items()
            for s in info.symbols.values()
        ],
    )
    w.create_edges(
        Edge.CALLS,
        [
            (sym(cm, cs), sym(tm, ts))
            for (cm, cs, tm, ts) in graph.internal_calls
        ],
    )
    w.create_edges(
        Edge.IMPORTS,
        [(module_key(pkg, ver, a), module_key(pkg, ver, b)) for a, b in graph.module_imports],
    )
    w.create_edges(
        Edge.IMPORTS,
        [(module_key(pkg, ver, m), package_key("npm", p)) for m, p in graph.package_imports],
    )

    log.info("emitted %s", w.summary())
    return w, graph.external_refs


def _looks_like_test(path: str) -> bool:
    lowered = path.lower()
    return (
        "/test/" in f"/{lowered}"
        or "/tests/" in f"/{lowered}"
        or "__tests__" in lowered
        or lowered.endswith((".test.ts", ".test.js", ".spec.ts", ".spec.js",
                             ".test.tsx", ".spec.tsx"))
    )


def entrypoint_keys(graph: ProjectGraph, *, include_tests: bool = False) -> list[str]:
    """Canonical keys of every symbol reachability should start from."""
    pkg, ver = graph.package_name, graph.package_version
    out = []
    for path, info in graph.modules.items():
        if not include_tests and _looks_like_test(path):
            continue
        for s in info.symbols.values():
            if s.exported or s.name == MODULE_SCOPE:
                out.append(symbol_key(pkg, ver, path, s.name))
    return out
