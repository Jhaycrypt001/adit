"""Stage D: cross the package boundary.

Your code says `import { merge } from 'lodash'`. The advisory says "prototype
pollution in `_.unset` and `_.omit`". Nothing connects those two facts until
somebody resolves the specifier to an installed version, parses *that package's*
source, builds *its* internal call graph, and binds the exported name to the
internal symbol the advisory implicates.

That join is the product. Everything before it is plumbing, and no public API
hands it to you -- deps.dev has never seen your source, and OSV has never seen
your imports.

**Lazy by design.** Only packages carrying an advisory are parsed, never the
whole `node_modules` tree. A typical project installs hundreds of packages and
has advisories on a handful, so this is the difference between seconds and
minutes -- and it is why Adit can run on a laptop during an incident.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from ..graph import Edge, Hydra, Label, Node, Writer
from ..graph.ids import module_key, package_key, symbol_key
from .lockfile import LockGraph, ResolvedPackage
from .osv import Advisory
from .project import ExternalRef, ProjectGraph, analyse
from .symbols import SymbolResolution, resolve

log = logging.getLogger(__name__)


@dataclass(slots=True)
class BoundAdvisory:
    """An advisory tied to concrete symbol keys in the graph."""

    advisory: Advisory
    package: ResolvedPackage
    resolution: SymbolResolution
    #: Canonical keys of the vulnerable symbols, as written to the graph.
    symbol_keys: list[str] = field(default_factory=list)
    #: Canonical keys of repo symbols that call into this package at all.
    entry_callers: list[str] = field(default_factory=list)


@dataclass
class BindResult:
    bound: list[BoundAdvisory] = field(default_factory=list)
    packages_parsed: int = 0
    packages_skipped: int = 0
    symbols_written: int = 0
    boundary_edges: int = 0

    def summary(self) -> str:
        tiers = {}
        for b in self.bound:
            tiers[b.resolution.tier] = tiers.get(b.resolution.tier, 0) + 1
        return (
            f"{len(self.bound)} advisories bound across {self.packages_parsed} packages, "
            f"{self.symbols_written:,} symbols, {self.boundary_edges} boundary edges, "
            f"tiers {dict(sorted(tiers.items()))}"
        )


def package_dir(node_modules_root: Path, pkg: ResolvedPackage) -> Path | None:
    """Locate a package on disk using the path the lockfile recorded."""
    candidate = node_modules_root / pkg.path
    if candidate.is_dir():
        return candidate
    flat = node_modules_root / "node_modules" / pkg.name
    return flat if flat.is_dir() else None


def bind(
    repo: ProjectGraph,
    external_refs: list[ExternalRef],
    lock: LockGraph,
    advisories_by_package: dict[str, list[Advisory]],
    project_root: Path,
    hydra: Hydra,
    *,
    http: httpx.Client | None = None,
    allow_network: bool = True,
) -> BindResult:
    """Parse vulnerable dependencies and wire them to the calls that reach them."""
    result = BindResult()
    writer = Writer(hydra)

    # Which installed package does each advisory-bearing name correspond to?
    installed: dict[str, ResolvedPackage] = {}
    for pkg in lock.packages.values():
        installed.setdefault(pkg.name, pkg)

    # Repo-side callers, grouped by (package, imported name).
    callers: dict[tuple[str, str], list[ExternalRef]] = {}
    for ref in external_refs:
        callers.setdefault((ref.package, ref.imported), []).append(ref)

    for pkg_name, advisories in advisories_by_package.items():
        pkg = installed.get(pkg_name)
        if pkg is None:
            result.packages_skipped += 1
            continue
        directory = package_dir(project_root, pkg)
        if directory is None:
            log.warning("%s@%s not found on disk; skipping", pkg.name, pkg.version)
            result.packages_skipped += 1
            continue

        # is_dependency=True: most published npm packages ship only compiled
        # output, often placed under dist/build/out with no parallel source to
        # double-count against -- pruning those (stage A's policy for the
        # project's own repo) silently zeroed uuid@8.3.2's entire public
        # surface. See project.py's analyse() docstring.
        dep = analyse(directory, is_dependency=True)
        # The lockfile is authoritative for identity; a dependency's own
        # package.json can disagree, and node keys must match what stage B wrote.
        dep.package_name, dep.package_version = pkg.name, pkg.version
        result.packages_parsed += 1

        exports = {
            s.name
            for info in dep.modules.values()
            for s in info.symbols.values()
            if s.exported
        }
        log.info("%s@%s: %d modules, %d exports", pkg.name, pkg.version,
                 len(dep.modules), len(exports))

        result.symbols_written += _write_package(writer, dep, pkg)

        for advisory in advisories:
            res = resolve(advisory, exports, client=http, allow_network=allow_network)
            bound = BoundAdvisory(advisory=advisory, package=pkg, resolution=res)

            # Where is each implicated symbol actually declared?
            for name in res.symbols:
                for path, info in dep.modules.items():
                    sym = info.symbols.get(name)
                    if sym is not None and sym.exported:
                        bound.symbol_keys.append(
                            symbol_key(pkg.name, pkg.version, path, name)
                        )
                        break

            # Join: every repo call site importing this name now points at the
            # package's own symbol, so a traversal can run straight through.
            edges: list[tuple[str, str]] = []
            for name in res.symbols:
                for ref in callers.get((pkg_name, name), []):
                    caller_key = symbol_key(
                        repo.package_name, repo.package_version, ref.module, ref.caller
                    )
                    target = next(
                        (k for k in bound.symbol_keys if k.endswith(f"#{name}")), None
                    )
                    if target is not None:
                        edges.append((caller_key, target))
                        bound.entry_callers.append(caller_key)
                # A namespace import (`import * as _ from 'lodash'`) reaches every
                # export, so it is a caller of this symbol too.
                for ref in callers.get((pkg_name, "*"), []):
                    caller_key = symbol_key(
                        repo.package_name, repo.package_version, ref.module, ref.caller
                    )
                    target = next(
                        (k for k in bound.symbol_keys if k.endswith(f"#{name}")), None
                    )
                    if target is not None:
                        edges.append((caller_key, target))
                        bound.entry_callers.append(caller_key)

            if edges:
                writer.create_edges(Edge.CALLS, edges)
                result.boundary_edges += len(edges)

            _write_advisory(writer, advisory, pkg, bound)
            result.bound.append(bound)

    log.info("stage D: %s", result.summary())
    return result


def _write_package(writer: Writer, dep: ProjectGraph, pkg: ResolvedPackage) -> int:
    """Persist a dependency's own modules, symbols and internal call graph."""
    name, version = pkg.name, pkg.version

    writer.upsert_nodes(
        [Node(key=package_key("npm", name), label=Label.PACKAGE,
              props={"name": name, "ecosystem": "npm"})]
    )
    writer.upsert_nodes(
        [Node(key=module_key(name, version, path), label=Label.MODULE,
              props={"path": path, "package": name, "version": version})
         for path in dep.modules]
    )

    symbols = [
        Node(
            key=symbol_key(name, version, path, s.name),
            label=Label.SYMBOL,
            props={
                "name": s.name,
                "kind": s.kind,
                "file": path,
                "line": s.line,
                "package": name,
                "version": version,
                "exported": s.exported,
                # A dependency's symbols are never repo entrypoints; reachability
                # starts in code you wrote.
                "entrypoint": False,
                "is_dependency": True,
            },
        )
        for path, info in dep.modules.items()
        for s in info.symbols.values()
    ]
    writer.upsert_nodes(symbols)

    # inverse=False: backward slicing ("what calls this?") is a question about
    # code you own, not about a dependency's internals. Skipping the materialised
    # inverse here halves the statement count for the largest edge set in the
    # scan, and each write statement costs roughly a second of durability commit
    # regardless of how many rows it carries.
    writer.create_edges(
        Edge.CALLS,
        [
            (symbol_key(name, version, cm, cs), symbol_key(name, version, tm, ts))
            for (cm, cs, tm, ts) in dep.internal_calls
        ],
        inverse=False,
    )
    writer.create_edges(
        Edge.EXPORTS,
        [
            (package_key("npm", name), symbol_key(name, version, path, s.name))
            for path, info in dep.modules.items()
            for s in info.symbols.values()
            if s.exported
        ],
    )
    return len(symbols)


def _write_advisory(
    writer: Writer, advisory: Advisory, pkg: ResolvedPackage, bound: BoundAdvisory
) -> None:
    writer.upsert_nodes(
        [
            Node(
                key=f"adv:{advisory.id}",
                label=Label.ADVISORY,
                props={
                    "advisory_id": advisory.id,
                    "summary": advisory.summary[:400],
                    "severity": advisory.severity or "unknown",
                    "klass": advisory.klass.value,
                    "package": pkg.name,
                    "version": pkg.version,
                    # The tier is carried to the CLI so a tier-3 guess is never
                    # presented with the confidence of a tier-1 fact.
                    "symbol_tier": bound.resolution.tier,
                    "symbol_confidence": bound.resolution.confidence,
                    "symbol_method": bound.resolution.method,
                },
            )
        ]
    )
    if bound.symbol_keys:
        writer.create_edges(
            Edge.VULNERABLE_SYMBOL,
            [(f"adv:{advisory.id}", k) for k in bound.symbol_keys],
            inverse=False,
        )
