"""Parse a lockfile into the exact dependency graph that was installed.

For the repository under analysis the lockfile is *authoritative* -- it records
what npm actually resolved, not what the manifest asked for. It is also offline
and exact, so it beats querying a registry for the same answer. deps.dev is used
for the different question of what the wider ecosystem depends on
(`depsdev.py`).

The subtle part is edge resolution. A lockfile lists installed packages by their
`node_modules` path, and a dependency name resolves by walking up from the
dependent's own directory -- `node_modules/a/node_modules/b` shadows
`node_modules/b`. Getting that wrong silently attaches edges to the wrong
version, which would make blast radius quietly incorrect rather than obviously
broken.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass(slots=True)
class ResolvedPackage:
    """One installed package, exactly as the lockfile pinned it."""

    name: str
    version: str
    path: str                      # "node_modules/foo/node_modules/bar"
    dev: bool = False
    integrity: str | None = None
    resolved_url: str | None = None
    #: npm records this when a package declares pre/post-install hooks. It is
    #: the install-time attack surface: such a package executes code at
    #: `npm install` whether or not anything ever imports it.
    has_install_script: bool = False

    @property
    def spec(self) -> str:
        return f"{self.name}@{self.version}"


@dataclass
class LockGraph:
    """The resolved dependency graph of one project."""

    root_name: str
    root_version: str
    lockfile: str
    lockfile_version: int
    packages: dict[str, ResolvedPackage] = field(default_factory=dict)  # by path
    #: (dependent path, dependency path)
    edges: list[tuple[str, str]] = field(default_factory=list)
    #: Direct dependencies of the root project.
    direct: set[str] = field(default_factory=set)
    unresolved_deps: int = 0

    def by_spec(self) -> dict[str, ResolvedPackage]:
        return {p.spec: p for p in self.packages.values()}

    @property
    def install_scripted(self) -> list[ResolvedPackage]:
        """Packages that run code at install time, in dependency order."""
        return sorted(
            (p for p in self.packages.values() if p.has_install_script),
            key=lambda p: p.name,
        )

    def summary(self) -> str:
        return (
            f"{len(self.packages):,} packages, {len(self.edges):,} dependency edges, "
            f"{len(self.direct)} direct, "
            f"{len(self.install_scripted)} with install scripts"
        )


def _name_from_path(path: str) -> str:
    """`node_modules/a/node_modules/@scope/b` -> `@scope/b`."""
    marker = "node_modules/"
    idx = path.rfind(marker)
    return path[idx + len(marker) :] if idx >= 0 else path


def _resolve(dep_name: str, from_path: str, packages: dict[str, ResolvedPackage]) -> str | None:
    """Apply node resolution: nearest `node_modules` wins, walking upward.

    From `node_modules/a/node_modules/b`, a dependency `c` is looked for at
    `node_modules/a/node_modules/b/node_modules/c`, then
    `node_modules/a/node_modules/c`, then `node_modules/c`.
    """
    prefix = from_path
    while True:
        candidate = f"{prefix}/node_modules/{dep_name}" if prefix else f"node_modules/{dep_name}"
        if candidate in packages:
            return candidate
        if not prefix:
            return None
        # Step out of the current package directory.
        marker = "/node_modules/"
        idx = prefix.rfind(marker)
        if idx < 0:
            prefix = ""
        else:
            prefix = prefix[:idx]


def parse_package_lock(path: Path) -> LockGraph:
    """Parse `package-lock.json` (lockfileVersion 2 or 3)."""
    # utf-8-sig tolerates a BOM, which Windows-authored files often carry.
    data = json.loads(path.read_text("utf-8-sig"))
    version = int(data.get("lockfileVersion", 0))

    graph = LockGraph(
        root_name=str(data.get("name") or path.parent.name),
        root_version=str(data.get("version") or "0.0.0"),
        lockfile=path.name,
        lockfile_version=version,
    )

    entries: dict = data.get("packages") or {}
    if not entries:
        # lockfileVersion 1 uses a nested "dependencies" tree instead. Rare on
        # anything current; declared unsupported rather than half-parsed.
        raise ValueError(
            f"{path.name} has lockfileVersion {version} with no `packages` map; "
            "only v2/v3 lockfiles are supported"
        )

    for pkg_path, meta in entries.items():
        if pkg_path == "":  # the root project itself
            for field_name in ("dependencies", "devDependencies", "optionalDependencies"):
                graph.direct.update((meta.get(field_name) or {}).keys())
            continue
        if not isinstance(meta, dict) or "version" not in meta:
            continue
        graph.packages[pkg_path] = ResolvedPackage(
            name=str(meta.get("name") or _name_from_path(pkg_path)),
            version=str(meta["version"]),
            path=pkg_path,
            dev=bool(meta.get("dev", False)),
            integrity=meta.get("integrity"),
            resolved_url=meta.get("resolved"),
            has_install_script=bool(meta.get("hasInstallScript", False)),
        )

    # Root -> direct dependencies.
    for dep in graph.direct:
        target = _resolve(dep, "", graph.packages)
        if target:
            graph.edges.append(("", target))
        else:
            graph.unresolved_deps += 1

    # Package -> package.
    for pkg_path, meta in entries.items():
        if pkg_path == "" or pkg_path not in graph.packages:
            continue
        declared: dict[str, str] = {}
        for field_name in ("dependencies", "optionalDependencies", "peerDependencies"):
            declared.update(meta.get(field_name) or {})
        for dep in declared:
            target = _resolve(dep, pkg_path, graph.packages)
            if target:
                graph.edges.append((pkg_path, target))
            else:
                # Optional and peer dependencies are legitimately absent.
                graph.unresolved_deps += 1

    log.info("parsed %s: %s", path.name, graph.summary())
    return graph


def find_lockfile(root: Path) -> Path | None:
    """Locate a supported lockfile, preferring the one npm writes."""
    for name in ("package-lock.json", "npm-shrinkwrap.json"):
        candidate = root / name
        if candidate.is_file():
            return candidate
    return None


def load(root: Path) -> LockGraph:
    """Parse the project's lockfile, or raise with an actionable message."""
    found = find_lockfile(root)
    if found is None:
        others = [n for n in ("yarn.lock", "pnpm-lock.yaml") if (root / n).is_file()]
        hint = f" (found {', '.join(others)}, not yet supported)" if others else ""
        raise FileNotFoundError(f"no package-lock.json in {root}{hint}")
    return parse_package_lock(found)
