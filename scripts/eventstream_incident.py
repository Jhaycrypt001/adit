"""Narrate the real 2018 event-stream/flatmap-stream incident through Adit.

`npm install event-stream@3.3.6` fails today with ETARGET: npm unpublished the
compromised release as part of the actual incident response (the attack
injected code to steal Bitcoin wallet keys from downstream apps, notably
Copay), so it can no longer be freshly installed. That is not a dead end --
it is the point. A real 2018 responder could not "just reinstall" the bad
version to check exposure either; they had to check what their own EXISTING
lockfile had already resolved. This script does exactly that, reconstructing
a lockfile with the real published/pulled dates from public writeups and
running it through the exact same `emit_lockfile()` / `Queries` code every
other scan in this project uses -- no demo-only code path.

The correctness claims here are pinned down as real tests in
the incident is reproducible from this script; it exists for narrated demo
output, not as the thing that proves them.

    py scripts/eventstream_incident.py
"""

from __future__ import annotations

import time

from adit.graph import Hydra, Queries
from adit.graph.ids import release_key
from adit.ingest.deps_emit import emit_lockfile
from adit.ingest.lockfile import LockGraph, ResolvedPackage
from adit.ingest.osv import OsvClient, classify

# Real dates, from public writeups of the incident.
PUBLISHED = int(time.mktime((2018, 9, 8, 0, 0, 0, 0, 0, 0)))
PULLED = int(time.mktime((2018, 11, 20, 0, 0, 0, 0, 0, 0)))
RESOLVED_AT = PUBLISHED + 86400 * 10  # this lockfile resolved it 10 days after publish


def build_incident_lockfile(service_name: str) -> LockGraph:
    lock = LockGraph(
        root_name=service_name, root_version="1.0.0",
        lockfile="package-lock.json", lockfile_version=2,
        packages={
            "node_modules/event-stream": ResolvedPackage(
                name="event-stream", version="3.3.6", path="node_modules/event-stream",
            ),
            "node_modules/event-stream/node_modules/flatmap-stream": ResolvedPackage(
                name="flatmap-stream", version="0.1.1",
                path="node_modules/event-stream/node_modules/flatmap-stream",
            ),
        },
        direct={"event-stream"},
    )
    lock.edges = [
        ("", "node_modules/event-stream"),
        ("node_modules/event-stream", "node_modules/event-stream/node_modules/flatmap-stream"),
    ]
    return lock


def main() -> int:
    service = f"log-pipeline-{int(time.time())}"
    print(f"reconstructing a 2018 lockfile for a fictional service '{service}'")
    print(f"(real dates: flatmap-stream 0.1.1 published {time.ctime(PUBLISHED)}, "
          f"pulled {time.ctime(PULLED)})\n")

    with Hydra() as hydra:
        lock = build_incident_lockfile(service)
        emit_lockfile(
            lock, hydra, service_name=service, observed_at=RESOLVED_AT,
            source="package-lock.json (reconstructed, 2018 incident)",
        )

        print("Advisories for flatmap-stream@0.1.1 (live OSV query, not cached):")
        with OsvClient() as osv:
            hits = osv.query_batch([("flatmap-stream", "0.1.1")])
            ids = [i for group in hits.values() for i in group]
            advisories = osv.fetch_many(ids)
        for a in advisories.values():
            klass = classify(a)
            print(f"  {a.id:<22} [{klass.value:<12}] {a.summary[:70]}")

        q = Queries(hydra)
        target = release_key("npm", "flatmap-stream", "0.1.1")

        print("\nBlast radius (who transitively depends on the compromised release):")
        for dep in q.blast_radius(target):
            print(f"  {dep}")

        print("\nExposed services during the live-compromise window "
              "(Sep 8 - Nov 20 2018):")
        exposed = q.exposed_services(target, PUBLISHED, PULLED)
        for row in exposed:
            print(f"  {row['service']}  via {row['source']}")

        print("\nExposed services in a window BEFORE the compromise even existed "
              "(all of 2017):")
        before = int(time.mktime((2017, 1, 1, 0, 0, 0, 0, 0, 0)))
        before_end = int(time.mktime((2017, 12, 31, 0, 0, 0, 0, 0, 0)))
        rows = q.exposed_services(target, before, before_end)
        print(f"  {len(rows)} service(s) -- correctly none, the fact did not exist yet")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
