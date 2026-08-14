"""Can Adit name the vulnerable *function* for real advisories?

The subsystem that decides whether reachability is real. Runs the three-tier
resolver against live OSV data and a package parsed from disk, and reports which
tier each advisory landed on.

A result on tier 3 is not a failure -- it is the honest answer when nothing
names the function -- but a run that is *all* tier 3 means reachability has
degraded to package-level alerting and the product claim weakens accordingly.

    py scripts/probe_symbols.py <node_modules/pkg> <name> <version>
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

from adit.ingest.osv import OsvClient, classify
from adit.ingest.project import analyse
from adit.ingest.symbols import resolve


def main() -> int:
    if len(sys.argv) < 4:
        print(__doc__)
        return 2
    pkg_dir, name, version = Path(sys.argv[1]), sys.argv[2], sys.argv[3]

    print(f"parsing {name}@{version} from {pkg_dir} ...")
    graph = analyse(pkg_dir)
    exports = {
        s.name
        for info in graph.modules.values()
        for s in info.symbols.values()
        if s.exported
    }
    print(f"  {len(graph.modules):,} modules, {len(exports):,} exported symbols\n")

    with OsvClient() as osv:
        hits = osv.query_batch([(name, version)])
        ids = [i for group in hits.values() for i in group]
        advisories = osv.fetch_many(ids)

        print(f"{len(advisories)} advisories for {name}@{version}\n")
        tiers: Counter[int] = Counter()

        for advisory in advisories.values():
            klass = classify(advisory)
            res = resolve(advisory, exports)
            tiers[res.tier] += 1

            print(f"  {advisory.id}  [{klass.value}]")
            print(f"    {advisory.summary[:80]}")
            print(f"    tier {res.tier}: {res.describe()[:110]}")
            if res.tier < 3 and res.rejected:
                print(f"    rejected (not real exports): {', '.join(res.rejected[:6])}")
            print()

    print("tier distribution:")
    for tier in (1, 2, 3):
        if tiers[tier]:
            label = {1: "prose named it", 2: "patch revealed it", 3: "fell back to public API"}
            print(f"  tier {tier}  {tiers[tier]:>3}   {label[tier]}")

    resolved = tiers[1] + tiers[2]
    print(f"\n{resolved}/{sum(tiers.values())} advisories resolved to specific symbols")
    return 0 if resolved else 1


if __name__ == "__main__":
    raise SystemExit(main())
