"""Pass 2: resolve specifiers, follow re-exports, and bind call sites.

Pass 1 recorded what each file says. This pass works out what those statements
*refer to*, which needs the whole project in memory:

  1. resolve every import specifier to a real file, or to an external package
  2. build each module's export map, following re-export chains and barrel files
  3. bind each call site to the symbol it actually reaches

Step 3 is the one naive tools skip. `merge()` in `normalize.ts` is meaningless
until you know it was imported from `lodash`, that `lodash` is external, and
which of lodash's exports it corresponds to -- and a barrel file can put three
hops between the import and the declaration.

Calls that cannot be bound are counted, not guessed. An honest "unresolved"
number is what lets the limitations section in the README be true.
"""

from __future__ import annotations

import json
import logging
import os
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .typescript import MODULE_SCOPE, ModuleInfo, parse_file

log = logging.getLogger(__name__)

#: Tried in order when a relative specifier has no extension. Order matters:
#: TypeScript wins over JavaScript because a project shipping both has the .js
#: as build output, and binding to build output would double-count the graph.
_EXTENSIONS = (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs")
_INDEXES = tuple(f"index{ext}" for ext in _EXTENSIONS)

_SKIP_DIRS = {
    "node_modules", ".git", "dist", "build", "out", "coverage",
    ".next", ".turbo", ".cache", "vendor", "__pycache__",
}


@dataclass(slots=True)
class ExternalRef:
    """A call that leaves the repository for an external package.

    Deliberately *not* bound to a symbol key here. The package version is not
    known until the lockfile is read (stage B), and the target symbol is not
    known until the package's own source is parsed (stage D). Emitting a
    placeholder key now would mean rewriting node identity later, and node ids
    are hashes of keys -- so we carry the facts and bind once, correctly.
    """

    module: str          # importing module, repo-relative
    caller: str          # symbol containing the call
    package: str         # bare package name, e.g. "lodash" or "@scope/pkg"
    subpath: str         # "" or "merge" for "lodash/merge"
    imported: str        # exported name in the package; "*" or "default"
    line: int


@dataclass
class ProjectGraph:
    """The resolved result of analysing a repository."""

    root: Path
    package_name: str
    package_version: str
    modules: dict[str, ModuleInfo] = field(default_factory=dict)
    #: (caller_module, caller_symbol, callee_module, callee_symbol)
    internal_calls: list[tuple[str, str, str, str]] = field(default_factory=list)
    #: (module, specifier-resolved module)
    module_imports: list[tuple[str, str]] = field(default_factory=list)
    #: (module, package)
    package_imports: list[tuple[str, str]] = field(default_factory=list)
    external_refs: list[ExternalRef] = field(default_factory=list)

    unresolved_calls: int = 0
    resolved_calls: int = 0
    parse_errors: int = 0
    #: Why call sites failed to bind, so the figure can be explained, not just quoted.
    unresolved_reasons: Counter[str] = field(default_factory=Counter)

    @property
    def bind_rate(self) -> float:
        """Share of call sites bound to a target, internal or external.

        External refs count as bound because the target *is* determined -- a
        specific export of a specific package. Only the node key is deferred
        until the version is known. `internal_bind_rate` excludes them.
        """
        total = self.resolved_calls + self.unresolved_calls
        return self.resolved_calls / total if total else 0.0

    @property
    def internal_bind_rate(self) -> float:
        """Share bound to a symbol *inside this repository*."""
        total = self.resolved_calls + self.unresolved_calls
        return len(self.internal_calls) / total if total else 0.0

    def summary(self) -> str:
        symbols = sum(len(m.symbols) for m in self.modules.values())
        return (
            f"{len(self.modules):,} modules, {symbols:,} symbols, "
            f"{len(self.internal_calls):,} internal calls, "
            f"{len(self.external_refs):,} external refs, "
            f"{self.bind_rate:.0%} of call sites bound"
        )


def _is_relative(specifier: str) -> bool:
    return specifier.startswith(".")


def split_package(specifier: str) -> tuple[str, str]:
    """Split a bare specifier into (package, subpath).

    Scoped packages keep two segments: `@scope/pkg/deep` -> (`@scope/pkg`, `deep`).
    """
    parts = specifier.split("/")
    if specifier.startswith("@") and len(parts) >= 2:
        return "/".join(parts[:2]), "/".join(parts[2:])
    return parts[0], "/".join(parts[1:])


class Resolver:
    """Resolves specifiers and export chains for one project."""

    def __init__(self, modules: dict[str, ModuleInfo], root: Path) -> None:
        self.modules = modules
        self.root = root
        self._cache: dict[tuple[str, str], str | None] = {}

    def resolve_specifier(self, from_module: str, specifier: str) -> str | None:
        """Map a relative specifier to a repo-relative module path, or None."""
        if not _is_relative(specifier):
            return None
        cached = self._cache.get((from_module, specifier))
        if cached is not None or (from_module, specifier) in self._cache:
            return cached

        # normpath, not Path: pathlib will not collapse ".." without touching
        # the filesystem, so "src/api/../lib" would stay literal and every
        # parent-relative import would silently fail to resolve. On Windows
        # normpath also flips separators, hence the replace.
        base = os.path.normpath((Path(from_module).parent / specifier).as_posix())
        base = base.replace("\\", "/")
        candidates = [base, *(f"{base}{ext}" for ext in _EXTENSIONS)]
        candidates += [f"{base}/{idx}" for idx in _INDEXES]
        # A specifier written with a .js extension in a TS project refers to the
        # .ts source; this is standard NodeNext practice and missing it silently
        # severs whole subtrees of the call graph.
        if base.endswith(".js"):
            stem = base[:-3]
            candidates[1:1] = [f"{stem}.ts", f"{stem}.tsx"]

        found = next((c for c in candidates if c in self.modules), None)
        self._cache[(from_module, specifier)] = found
        return found

    def resolve_export(
        self, module: str, name: str, _seen: frozenset[str] = frozenset()
    ) -> tuple[str, str] | None:
        """Find where `module`'s export `name` is actually declared.

        Follows aliases, re-export chains and `export * from` barrels. Returns
        (declaring_module, local_symbol_name), or None if it leaves the repo or
        cannot be found.
        """
        if module in _seen:  # circular barrels are legal and do occur
            return None
        info = self.modules.get(module)
        if info is None:
            return None
        seen = _seen | {module}

        binding = info.exports.get(name)
        if binding is not None:
            if binding.local is not None:
                if binding.local in info.symbols:
                    return module, binding.local
                # Exported name declared by an import: `import {a} from './x';
                # export {a}` -- keep following.
                imported = info.imports.get(binding.local)
                if imported is not None:
                    target = self.resolve_specifier(module, imported.source)
                    if target:
                        return self.resolve_export(target, imported.imported, seen)
                return None
            if binding.source is not None and binding.imported is not None:
                target = self.resolve_specifier(module, binding.source)
                if target:
                    return self.resolve_export(target, binding.imported, seen)
                return None

        # Not named explicitly -- try the star re-exports in order.
        for specifier in info.star_reexports:
            target = self.resolve_specifier(module, specifier)
            if target:
                hit = self.resolve_export(target, name, seen)
                if hit is not None:
                    return hit

        # Some projects export without an explicit clause; if the symbol exists
        # here and is marked exported, that is good enough.
        symbol = info.symbols.get(name)
        if symbol is not None and symbol.exported:
            return module, name
        return None


def _walk_sources(root: Path, max_files: int):
    """Yield source files, pruning skipped directories *during* the walk.

    `rglob("*")` then filtering means descending into `node_modules` and
    enumerating every file in it before discarding them -- which on a project
    with a populated dependency tree dominates parse time and looks like slow
    parsing rather than a wasted walk. os.walk lets us prune in place.

    Results are sorted per directory so ingest is deterministic: node ids are
    hashes of keys, and "first declaration wins" for duplicate names.
    """
    yielded = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        for filename in sorted(filenames):
            if Path(filename).suffix not in _BY_SUFFIX_KEYS:
                continue
            yield Path(dirpath) / filename
            yielded += 1
            if yielded >= max_files:
                return


def _read_package_json(root: Path) -> tuple[str, str]:
    try:
        # utf-8-sig, not utf-8: Windows-authored JSON routinely carries a BOM,
        # and json.loads rejects it. Silently falling back to the directory name
        # would mislabel every symbol key in the graph.
        data = json.loads((root / "package.json").read_text("utf-8-sig"))
        return str(data.get("name") or root.name), str(data.get("version") or "0.0.0")
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("could not read %s/package.json (%s); using directory name", root, exc)
        return root.name, "0.0.0"


def analyse(root: Path, *, max_files: int = 20_000) -> ProjectGraph:
    """Parse and resolve a repository into a bindable call graph."""
    root = root.resolve()
    name, version = _read_package_json(root)
    graph = ProjectGraph(root=root, package_name=name, package_version=version)

    # -- pass 1 ------------------------------------------------------------
    count = 0
    for path in _walk_sources(root, max_files):
        if count >= max_files:
            log.warning("stopped at max_files=%d", max_files)
            break
        info = parse_file(path, root)
        if info is None:
            continue
        graph.modules[info.path] = info
        graph.parse_errors += info.parse_errors
        count += 1

    resolver = Resolver(graph.modules, root)

    # -- pass 2 ------------------------------------------------------------
    for path, info in graph.modules.items():
        for specifier in info.specifiers():
            target = resolver.resolve_specifier(path, specifier)
            if target:
                graph.module_imports.append((path, target))
            elif not _is_relative(specifier):
                graph.package_imports.append((path, split_package(specifier)[0]))

        for symbol in info.symbols.values():
            for call in symbol.calls:
                _bind(graph, resolver, info, symbol.name, call)

    return graph


def _resolve_method(
    graph: ProjectGraph,
    resolver: Resolver,
    info: ModuleInfo,
    caller: str,
    cls: str,
    member: str,
) -> bool:
    """Bind `Class.member`, whether Class is declared here or imported."""
    module = info.path
    local = f"{cls}.{member}"
    if local in info.symbols:
        graph.internal_calls.append((module, caller, module, local))
        graph.resolved_calls += 1
        return True

    binding = info.imports.get(cls)
    if binding is None or not _is_relative(binding.source):
        return False
    target = resolver.resolve_specifier(module, binding.source)
    if not target:
        return False
    # Resolve the class through re-exports, then look for the method on the
    # module that actually declares it -- a barrel can sit in between.
    hit = resolver.resolve_export(target, binding.imported)
    if hit is None:
        return False
    declaring, declared_cls = hit
    candidate = f"{declared_cls}.{member}"
    if candidate in graph.modules[declaring].symbols:
        graph.internal_calls.append((module, caller, declaring, candidate))
        graph.resolved_calls += 1
        return True
    return False


def _bind(graph: ProjectGraph, resolver: Resolver, info: ModuleInfo, caller: str, call) -> None:
    """Bind one call site, or record it as unresolved."""
    module = info.path

    # `ns.member()` where ns is a namespace import -- resolve member in target.
    if call.base is not None:
        binding = info.imports.get(call.base)
        if binding is not None and call.member:
            if _is_relative(binding.source):
                target = resolver.resolve_specifier(module, binding.source)
                if target:
                    hit = resolver.resolve_export(target, call.member)
                    if hit is not None:
                        graph.internal_calls.append((module, caller, hit[0], hit[1]))
                        graph.resolved_calls += 1
                        return
            else:
                pkg, subpath = split_package(binding.source)
                graph.external_refs.append(
                    ExternalRef(module, caller, pkg, subpath, call.member, call.line)
                )
                graph.resolved_calls += 1
                return
        # `this.method()` inside a class binds to that class's method. Cheap,
        # common, and safe -- the class name is lexically known from the caller.
        if call.base == "this" and "." in caller and call.member:
            cls = caller.split(".", 1)[0]
            candidate = f"{cls}.{call.member}"
            if candidate in info.symbols:
                graph.internal_calls.append((module, caller, module, candidate))
                graph.resolved_calls += 1
                return

        # `const svc = new OrderService(); svc.handle()` -- the class was
        # recorded at parse time, so resolve it the same way any other name is
        # resolved: locally first, then through imports.
        cls = info.local_types.get((caller, call.base))
        if cls is not None and call.member:
            if _resolve_method(graph, resolver, info, caller, cls, call.member):
                return

        # Anything else (obj.method() on a value we cannot type) stays unbound.
        graph.unresolved_calls += 1
        graph.unresolved_reasons["member call on untyped receiver"] += 1
        return

    name = call.name

    # Local declaration wins.
    if name in info.symbols:
        graph.internal_calls.append((module, caller, module, name))
        graph.resolved_calls += 1
        return

    binding = info.imports.get(name)
    if binding is None:
        # Globals, built-ins (console, JSON, Promise), locally-defined closures
        # we do not model, or dynamically produced callables.
        graph.unresolved_calls += 1
        graph.unresolved_reasons["undeclared name (global/builtin/local closure)"] += 1
        return

    if _is_relative(binding.source):
        target = resolver.resolve_specifier(module, binding.source)
        if target is None:
            graph.unresolved_calls += 1
            graph.unresolved_reasons["specifier resolved to no file"] += 1
            return
        hit = resolver.resolve_export(target, binding.imported)
        if hit is not None:
            graph.internal_calls.append((module, caller, hit[0], hit[1]))
            graph.resolved_calls += 1
            return
        graph.unresolved_calls += 1
        graph.unresolved_reasons["export not found in target module"] += 1
        return

    pkg, subpath = split_package(binding.source)
    graph.external_refs.append(
        ExternalRef(module, caller, pkg, subpath, binding.imported, call.line)
    )
    graph.resolved_calls += 1


# Imported late to avoid a circular import at module load.
from .typescript import _BY_SUFFIX as _BY_SUFFIX_MAP  # noqa: E402

_BY_SUFFIX_KEYS = frozenset(_BY_SUFFIX_MAP)

__all__ = ["ExternalRef", "ProjectGraph", "Resolver", "analyse", "split_package", "MODULE_SCOPE"]
