"""End-to-end check of the lockfile -> OSV -> classification path, live.

Proves acceptance criterion A2: real advisory data, not a checked-in snapshot.
Also shows the install-time/runtime split, which is the decision that selects
which query Adit runs.

    py scripts/probe_advisories.py <project-with-package-lock.json>
"""

from __future__ import annotations

import sys
import time
from collections import Counter
from pathlib import Path

from adit.graph.schema import AdvisoryClass
from adit.ingest import lockfile
from adit.ingest.osv import OsvClient, classify


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    root = Path(sys.argv[1])

    lock = lockfile.load(root)
    print(f"{lock.root_name}@{lock.root_version}  (lockfileVersion {lock.lockfile_version})")
    print(f"  {lock.summary()}")
    if lock.unresolved_deps:
        print(f"  {lock.unresolved_deps} declared deps not installed (optional/peer)")

    scripted = {p.spec for p in lock.install_scripted}
    if scripted:
        print(f"  install scripts: {', '.join(sorted(scripted))}")

    specs = sorted({(p.name, p.version) for p in lock.packages.values()})
    print(f"\nquerying OSV for {len(specs)} package versions ...")

    started = time.perf_counter()
    with OsvClient() as osv:
        hits = osv.query_batch(specs)
        ids = [i for group in hits.values() for i in group]
        advisories = osv.fetch_many(ids)
    elapsed = time.perf_counter() - started

    print(f"  {len(hits)} vulnerable package versions, "
          f"{len(advisories)} unique advisories  ({elapsed:.1f}s)\n")

    counts: Counter[AdvisoryClass] = Counter()
    for spec, advisory_ids in sorted(hits.items()):
        name, version = spec
        has_script = any(
            p.has_install_script for p in lock.packages.values()
            if p.name == name and p.version == version
        )
        print(f"  {name}@{version}" + ("   [has install script]" if has_script else ""))
        for advisory_id in advisory_ids:
            advisory = advisories.get(advisory_id)
            if advisory is None:
                continue
            klass = classify(advisory, has_install_script=has_script)
            counts[klass] += 1
            fixes = advisory.fix_references()
            print(f"    {advisory_id:<22} {klass.value:<12} {advisory.summary[:58]}")
            if fixes:
                print(f"      {len(fixes)} patch reference(s), first: {fixes[0][:76]}")

    print("\nclassification:")
    for klass, n in counts.most_common():
        question = (
            "blast radius + temporal window"
            if klass is AdvisoryClass.INSTALL_TIME
            else "reachability"
        )
        print(f"  {klass.value:<14} {n:>3}   -> {question}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
