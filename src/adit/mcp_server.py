"""Adit as an MCP server: `adit trace` for an agent instead of a terminal.

Five tools, deliberately few. Teams routinely burn 20-70% of a context window
on tool schemas before an agent does any work, so this surface is kept to
exactly what a reachability question needs -- not a wrapper around every method
`Queries` exposes.

Canonical symbol keys (`sym:pkg@ver:file#name`) are Adit's internal identity,
not something an agent calling this server would know. `find_symbol` is the
lookup an agent is expected to call first; the other tools accept either a
resolved key or a bare name and resolve it themselves, so a well-behaved agent
never has to think about the key format at all.

    adit-mcp                       stdio transport (Claude Code, Cursor, ...)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from .graph import Edge, Hydra, Label, Queries
from .graph.ids import release_key
from .render import to_json
from .scan import scan

log = logging.getLogger(__name__)

server = MCPServer(
    name="adit",
    version="0.1.0",
    instructions=(
        "Adit answers one question over a graph: does a path exist from A to B, "
        "and if so what is it. Primary use: given a repository, which of its "
        "dependency CVEs are actually reachable from code that runs, as opposed "
        "to merely installed. Call trace_repository first -- it ingests the repo "
        "and answers every advisory in one pass. Use find_symbol to resolve a "
        "human name to the exact key the other tools need."
    ),
)


def _hydra() -> Hydra:
    return Hydra()


def _resolve_symbol(hydra: Hydra, name_or_key: str) -> str | None:
    """Accept either an exact canonical key or a bare symbol name."""
    q = Queries(hydra)
    if name_or_key.startswith("sym:") and q.key_exists(name_or_key):
        return name_or_key
    rows = hydra.run(
        f"MATCH (n:{Label.SYMBOL.value}) WHERE n.name = $name RETURN n.key AS key LIMIT 1",
        name=name_or_key,
    )
    return rows[0]["key"] if rows else None


@server.tool()
def trace_repository(path: str, offline: bool = False) -> dict[str, Any]:
    """Ingest a TypeScript/JavaScript repository and answer every dependency
    advisory: which are actually reachable from your code, which are correctly
    not, and for install-time compromises, the blast radius instead. This is
    the primary tool -- run it before find_symbol, why_reachable, or callers_of,
    since those read the graph it writes.

    Args:
        path: Absolute path to the repository root (must contain package-lock.json).
        offline: Skip network calls that only refine symbol confidence (tier 2).
    """
    root = Path(path).resolve()
    if not root.is_dir():
        return {"error": f"{root} is not a directory"}
    with _hydra() as hydra:
        report = scan(root, hydra, allow_network=not offline)
    return to_json(report)


@server.tool()
def why_reachable(source: str, target: str, max_len: int = 12) -> dict[str, Any]:
    """Explain whether `source` can reach `target` through the call graph, and
    show the exact path if so. Either argument may be a canonical symbol key or
    a bare function/method name (resolved automatically; ambiguous names
    resolve to the first match, so prefer find_symbol first when precision
    matters). A false "not reachable" is worse than no answer, so this returns
    the search bound it used whenever nothing is found rather than staying
    silent about it.

    Args:
        source: Canonical key or name of the starting symbol (usually an entrypoint).
        target: Canonical key or name of the symbol to reach.
        max_len: Maximum call-graph hops to search.
    """
    with _hydra() as hydra:
        q = Queries(hydra)
        src = _resolve_symbol(hydra, source)
        tgt = _resolve_symbol(hydra, target)
        if src is None:
            return {"error": f"no symbol found matching {source!r}"}
        if tgt is None:
            return {"error": f"no symbol found matching {target!r}"}

        result = q.reachability([src], [tgt], max_len=max_len)
        if not result.reachable:
            return {"reachable": False, "explanation": result.explain_absence()}
        path = result.shortest
        return {
            "reachable": True,
            "depth": path.depth,
            "path": [
                {"name": n.get("name"), "file": n.get("file"), "line": n.get("line")}
                for n in path.nodes
            ],
        }


@server.tool()
def blast_radius(package_spec: str, max_len: int = 10) -> dict[str, Any]:
    """For a compromised package release, find every package that transitively
    depends on it AND every service that actually resolved that exact version
    in its lockfile. Use this for install-time compromises (a malicious
    preinstall/postinstall script) where reachability through the call graph is
    the wrong question -- the payload runs at `npm install` regardless of
    whether anything imports the package.

    Args:
        package_spec: "<package>@<version>", e.g. "keyv@5.5.4".
    """
    try:
        name, version = package_spec.rsplit("@", 1)
    except ValueError:
        return {"error": "expected <package>@<version>, e.g. keyv@5.5.4"}
    with _hydra() as hydra:
        q = Queries(hydra)
        target = release_key("npm", name, version)
        if not q.key_exists(target):
            return {"error": f"{package_spec} is not in the graph -- run trace_repository first"}
        return {
            "package": package_spec,
            "dependent_packages": q.blast_radius(target, rel=Edge.DEPENDS_ON, max_len=max_len),
            "exposed_services": q.exposed_services(target),
        }


@server.tool()
def callers_of(symbol: str, max_len: int = 8) -> dict[str, Any]:
    """Backward slice: every symbol that transitively calls `symbol`. Answers
    "what breaks if I change this" -- a question similarity search cannot
    answer, because two functions that look alike need not have any call edge
    between them.

    Args:
        symbol: Canonical key or bare name of the symbol to check.
        max_len: Maximum hops to search backward.
    """
    with _hydra() as hydra:
        q = Queries(hydra)
        key = _resolve_symbol(hydra, symbol)
        if key is None:
            return {"error": f"no symbol found matching {symbol!r}"}
        return {"symbol": key, "callers": q.callers_of(key, max_len=max_len)}


@server.tool()
def find_symbol(name: str, limit: int = 20) -> dict[str, Any]:
    """Look up symbols by name after trace_repository has ingested a
    repository. Returns each match's canonical key, file, and line, so results
    can be passed directly to why_reachable or callers_of and so an ambiguous
    name (the same function name declared in several files) can be
    disambiguated by file before asking a reachability question.

    Args:
        name: Exact symbol name to search for (case-sensitive).
        limit: Maximum matches to return.
    """
    with _hydra() as hydra:
        rows = hydra.run(
            f"MATCH (n:{Label.SYMBOL.value}) WHERE n.name = $name "
            f"RETURN n.key AS key, n.file AS file, n.line AS line, "
            f"n.package AS package, n.exported AS exported LIMIT {int(limit)}",
            name=name,
        )
    return {"matches": rows}


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    server.run()


if __name__ == "__main__":
    main()
