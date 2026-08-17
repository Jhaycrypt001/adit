"""The pipeline: repository in, ranked findings out.

Stages A through E in order, then the query that each advisory's class demands:

    runtime      -> reachability. Blast radius is noise; everyone depends on
                    lodash. The question is whether *your* code reaches the
                    vulnerable function.
    install-time -> blast radius. Reachability is meaningless; a preinstall hook
                    runs at `npm install` whether or not anything imports it.

Getting that fork right is most of what separates a ranked answer from a wall of
alerts.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from .graph import Edge, Hydra, Queries, ReachPath
from .graph.schema import AdvisoryClass
from .ingest import lockfile
from .ingest.binder import BindResult, bind
from .ingest.deps_emit import emit_lockfile
from .ingest.emit import emit, entrypoint_keys
from .ingest.lockfile import LockGraph, ResolvedPackage
from .ingest.osv import Advisory, OsvClient, classify
from .ingest.project import ProjectGraph, analyse
from .ingest.symbols import SymbolResolution

log = logging.getLogger(__name__)


class Status(StrEnum):
    """Three distinct claims, not two -- collapsing them is the overclaim.

    REACHABLE and NOT_REACHABLE are both searches that completed: MSpaths ran
    against real symbol keys and returned a path, or returned none. UNRESOLVED
    means the search never ran at all, because there was no symbol key to
    search for -- found on express's uuid@8.3.2 dependency, whose entire
    published source lives under `dist/` and was, before that was fixed,
    invisible to the parser. Reporting that as "not reachable" would have
    claimed a search that never happened; the CLI and MCP renderers must never
    fold UNRESOLVED into either reachable outcome.
    """

    REACHABLE = "reachable"
    NOT_REACHABLE = "not_reachable"
    UNRESOLVED = "unresolved"


@dataclass(slots=True)
class Finding:
    """One advisory, answered."""

    advisory: Advisory
    package: ResolvedPackage
    klass: AdvisoryClass
    status: Status
    paths: list[ReachPath] = field(default_factory=list)
    blast: list[str] = field(default_factory=list)
    resolution: SymbolResolution | None = None
    reason: str = ""

    @property
    def reachable(self) -> bool:
        return self.status is Status.REACHABLE

    @property
    def actionable(self) -> bool:
        """Worth a human's attention today."""
        if self.klass is AdvisoryClass.INSTALL_TIME:
            return True  # it already ran
        return self.status is not Status.NOT_REACHABLE  # REACHABLE or UNRESOLVED

    @property
    def confidence(self) -> float:
        return self.resolution.confidence if self.resolution else 0.0

    def sort_key(self) -> tuple:
        # Actionable first, then most-confident, then shortest path -- a short
        # path is easier to verify by hand, which is what earns trust.
        depth = min((p.depth for p in self.paths), default=99)
        return (not self.actionable, -self.confidence, depth)


@dataclass
class ScanReport:
    root: Path
    repo: ProjectGraph
    lock: LockGraph
    findings: list[Finding] = field(default_factory=list)
    bind_result: BindResult | None = None
    elapsed: float = 0.0
    timings: dict[str, float] = field(default_factory=dict)

    @property
    def reachable(self) -> list[Finding]:
        return [f for f in self.findings if f.actionable]

    @property
    def not_reachable(self) -> list[Finding]:
        return [f for f in self.findings if not f.actionable]

    def headline(self) -> str:
        total, hot = len(self.findings), len(self.reachable)
        return f"{total} advisories affecting this repo, {hot} actionable"


def scan(
    root: Path,
    hydra: Hydra,
    *,
    max_len: int = 12,
    allow_network: bool = True,
) -> ScanReport:
    """Run the full pipeline against a project directory."""
    root = root.resolve()
    started = time.perf_counter()
    timings: dict[str, float] = {}

    def mark(label: str, since: float) -> float:
        now = time.perf_counter()
        timings[label] = now - since
        return now

    # -- A: the repository's own call graph --------------------------------
    t = time.perf_counter()
    repo = analyse(root)
    log.info("stage A: %s", repo.summary())
    t = mark("A parse repo", t)

    _, external_refs = emit(repo, hydra)
    t = mark("A write repo", t)

    # -- B: exactly what was installed -------------------------------------
    lock = lockfile.load(root)
    log.info("stage B: %s", lock.summary())

    # No package registry stamps a lockfile with an install date, so its own
    # mtime is the best available signal for "when was this resolution valid
    # from" without shelling out to git. A caller with a better timestamp (a
    # commit date, a CI build time) can override by writing the fact directly.
    lockfile_path = lockfile.find_lockfile(root)
    observed_at = int(lockfile_path.stat().st_mtime) if lockfile_path else int(time.time())
    emit_lockfile(lock, hydra, service_name=repo.package_name, observed_at=observed_at)
    t = mark("B write deps", t)

    # -- C: advisories ------------------------------------------------------
    specs = sorted({(p.name, p.version) for p in lock.packages.values()})
    with OsvClient() as osv:
        hits = osv.query_batch(specs)
        advisories = osv.fetch_many([i for group in hits.values() for i in group])
    t = mark("C advisories", t)

    by_package: dict[str, list[Advisory]] = {}
    scripted = {(p.name, p.version): p.has_install_script for p in lock.packages.values()}
    for (name, version), ids in hits.items():
        for advisory_id in ids:
            advisory = advisories.get(advisory_id)
            if advisory is None:
                continue
            advisory.klass = classify(
                advisory, has_install_script=scripted.get((name, version), False)
            )
            by_package.setdefault(name, []).append(advisory)

    # -- D: cross the package boundary -------------------------------------
    bind_result = bind(
        repo, external_refs, lock, by_package, root, hydra, allow_network=allow_network
    )
    t = mark("D bind", t)

    # -- answer each advisory with the right question ----------------------
    queries = Queries(hydra)
    roots = entrypoint_keys(repo)
    findings: list[Finding] = []

    for bound in bind_result.bound:
        advisory, pkg, res = bound.advisory, bound.package, bound.resolution

        if advisory.klass is AdvisoryClass.INSTALL_TIME:
            # The payload already executed. What matters is who pulled it in.
            blast = queries.blast_radius(f"pkg:npm:{pkg.name}", rel=Edge.DEPENDS_ON)
            findings.append(
                Finding(
                    advisory=advisory, package=pkg, klass=advisory.klass,
                    status=Status.REACHABLE, blast=blast, resolution=res,
                    reason="install script executes regardless of imports",
                )
            )
            continue

        if not bound.symbol_keys:
            # Not the same claim as NOT_REACHABLE: no search ran, because there
            # was no symbol key to search for. Reporting this as "not
            # reachable" would claim a search that never happened -- the exact
            # failure mode found on express's uuid@8.3.2 before the dist/
            # skip-dir bug was fixed (see project.py's analyse() docstring).
            findings.append(
                Finding(
                    advisory=advisory, package=pkg, klass=advisory.klass,
                    status=Status.UNRESOLVED, resolution=res,
                    reason="vulnerable symbol not located in the installed package "
                    "-- reachability was not checked",
                )
            )
            continue

        result = queries.reachability(roots, bound.symbol_keys, max_len=max_len)
        findings.append(
            Finding(
                advisory=advisory, package=pkg, klass=advisory.klass,
                status=Status.REACHABLE if result.reachable else Status.NOT_REACHABLE,
                paths=result.paths, resolution=res,
                reason="" if result.reachable else result.explain_absence(),
            )
        )

    mark("query", t)
    findings.sort(key=Finding.sort_key)

    return ScanReport(
        root=root, repo=repo, lock=lock, findings=findings,
        bind_result=bind_result, elapsed=time.perf_counter() - started,
        timings=timings,
    )
