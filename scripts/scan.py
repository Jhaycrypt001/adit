"""Run the full pipeline and print the findings.

    py scripts/scan.py <project-root>

The precursor to `adit trace`. Kept as a script so the pipeline can be exercised
end to end before the CLI surface is settled.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from adit.graph import Hydra
from adit.graph.schema import AdvisoryClass
from adit.scan import scan


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    logging.basicConfig(
        level=logging.INFO if "-v" in sys.argv else logging.WARNING,
        format="  %(levelname)s %(name)s: %(message)s",
    )

    root = Path(sys.argv[1])
    with Hydra() as hydra:
        report = scan(root, hydra)

    print(f"\n{report.repo.package_name}@{report.repo.package_version}   {report.root}")
    print(f"  {report.repo.summary()}")
    print(f"  {report.lock.summary()}")
    if report.bind_result:
        print(f"  stage D: {report.bind_result.summary()}")
    print()

    hot, cold = report.reachable, report.not_reachable
    print(f"  {len(report.findings)} advisories affecting this repo")
    print(f"  {len(hot)} ACTIONABLE")
    print(f"  {len(cold)} not reachable\n")

    for f in hot:
        marker = "!" if f.klass is AdvisoryClass.INSTALL_TIME else "x"
        print(f"  {marker} {f.advisory.id}  {f.package.spec}  [{f.klass.value}]")
        print(f"    {f.advisory.summary[:88]}")
        if f.resolution:
            print(f"    symbol: {f.resolution.describe()[:100]}")
        if f.klass is AdvisoryClass.INSTALL_TIME:
            print(f"    {f.reason}")
            if f.blast:
                print(f"    blast radius: {len(f.blast)} dependent(s)")
        for path in f.paths[:2]:
            print("    path:")
            for depth, node in enumerate(path.nodes):
                where = f"{node.get('file', '?')}:{node.get('line', '?')}"
                arrow = "   " if depth == 0 else "-> "
                tail = "   <- vulnerable" if depth == len(path.nodes) - 1 else ""
                print(f"      {'  ' * depth}{arrow}{node.get('name', '?')}  ({where}){tail}")
        print()

    if cold:
        print("  not reachable:")
        for f in cold:
            print(f"    - {f.advisory.id}  {f.package.spec}  ({f.reason[:70]})")

    print(f"\n  timings: " + ", ".join(f"{k} {v:.2f}s" for k, v in report.timings.items()))
    print(f"  total {report.elapsed:.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
