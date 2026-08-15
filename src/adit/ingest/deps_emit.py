"""Write a parsed lockfile into HydraDB as Releases, dependency edges, and
Resolution facts -- the data every install-time and temporal query depends on.

This was the missing half of stage B: `lockfile.load()` produced a `LockGraph`
in memory, but nothing persisted it, so `adit blast` had nothing to query and
the entire install-time story -- the reason Track 2A exists -- had no graph
behind it. Found by running `adit blast` against a real scan and getting zero
dependents on a package that plainly had one.

Two modelling choices worth stating:

**The project itself is a Release node.** Otherwise its direct dependencies
would need a different edge shape than every other package-to-package
dependency, and a transitive blast-radius chain reaching back to the root would
have nowhere to land. Uniform DEPENDS_ON edges mean `blast_radius()` needs no
special case for "am I looking at the root".

**A Resolution fact is written for every installed package, not just direct
dependencies.** An npm lockfile pins exact transitive versions -- that is the
whole point of a lockfile -- so "did this service resolve the bad version" is a
real, answerable question at any depth, not only for what the manifest names
directly.
"""

from __future__ import annotations

import logging

from ..graph import Edge, Fact, FactKind, Hydra, Label, Node, Provenance, Writer
from ..graph.ids import package_key, release_key, service_key
from .lockfile import LockGraph

log = logging.getLogger(__name__)


def emit_lockfile(
    lock: LockGraph,
    hydra: Hydra,
    *,
    service_name: str,
    observed_at: int,
    source: str = "package-lock.json",
) -> Writer:
    """Persist the resolved dependency graph and every resolution window.

    `service_name` identifies the project being scanned as the subject of the
    Resolution facts, so a later query for a compromised release can find it.
    """
    w = Writer(hydra)
    root_release = release_key("npm", lock.root_name, lock.root_version)

    releases = [
        Node(
            key=release_key("npm", p.name, p.version),
            label=Label.RELEASE,
            props={"name": p.name, "version": p.version, "ecosystem": "npm"},
        )
        for p in lock.packages.values()
    ]
    releases.append(
        Node(key=root_release, label=Label.RELEASE,
             props={"name": lock.root_name, "version": lock.root_version, "ecosystem": "npm"})
    )
    packages = [
        Node(key=package_key("npm", name), label=Label.PACKAGE,
             props={"name": name, "ecosystem": "npm"})
        for name in {p.name for p in lock.packages.values()} | {lock.root_name}
    ]
    w.upsert_nodes(packages)
    w.upsert_nodes(releases)
    w.upsert_nodes(
        [Node(key=service_key(service_name), label=Label.SERVICE, props={"name": service_name})]
    )

    def key_for(path: str) -> str | None:
        if path == "":
            return root_release
        pkg = lock.packages.get(path)
        return release_key("npm", pkg.name, pkg.version) if pkg else None

    dep_edges = [
        (src, dst)
        for src_path, dst_path in lock.edges
        if (src := key_for(src_path)) and (dst := key_for(dst_path))
    ]
    w.create_edges(Edge.DEPENDS_ON, dep_edges)

    # Every installed package, at the exact version the lockfile pinned it to --
    # this is what makes "did service X resolve the bad version, even
    # transitively" an answerable Q3 query rather than only a direct-dep one.
    facts = [
        Fact(
            kind=FactKind.RESOLUTION,
            subject_key=service_key(service_name),
            object_key=release_key("npm", p.name, p.version),
            provenance=Provenance(
                valid_from=observed_at, observed_at=observed_at, source=source
            ),
        )
        for p in lock.packages.values()
    ]
    w.upsert_facts(facts)

    log.info("stage B write: %s", w.summary())
    return w
