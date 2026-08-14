"""Measure extraction quality on repositories we did not write.

Acceptance criterion A1: fixtures prove the code runs; a foreign repo proves the
analysis works. The number that matters is the **bind rate** -- the share of
call sites resolved to a real target. A high symbol count with a low bind rate
means a graph full of orphans, which produces confident nonsense.

Unbound calls are not a bug per se: `console.log`, built-ins, and genuinely
dynamic dispatch are correctly unbindable. The point is to know the figure and
publish it rather than quietly imply 100%.

    py scripts/bench_extract.py <repo> [<repo> ...]
"""

from __future__ import annotations

import sys
import time
from collections import Counter
from pathlib import Path

from adit.ingest.project import analyse


def bench(root: Path) -> None:
    started = time.perf_counter()
    g = analyse(root)
    elapsed = time.perf_counter() - started

    symbols = sum(len(m.symbols) for m in g.modules.values())
    kinds = Counter(s.kind for m in g.modules.values() for s in m.symbols.values())
    exported = sum(
        1 for m in g.modules.values() for s in m.symbols.values() if s.exported
    )
    packages = {p for _, p in g.package_imports}

    print(f"\n{root.name}  ({g.package_name}@{g.package_version})")
    print("-" * 68)
    print(f"  modules            {len(g.modules):>8,}")
    print(f"  symbols            {symbols:>8,}   ({exported:,} exported)")
    print(f"  kinds              {dict(kinds.most_common())}")
    print(f"  internal calls     {len(g.internal_calls):>8,}")
    print(f"  external refs      {len(g.external_refs):>8,}   ({len(packages)} packages)")
    print(f"  module imports     {len(g.module_imports):>8,}")
    print(f"  BIND RATE          {g.bind_rate:>8.1%}   "
          f"({g.resolved_calls:,} bound / {g.unresolved_calls:,} unbound)")
    print(f"    of which internal{g.internal_bind_rate:>8.1%}")
    print(f"  parse errors       {g.parse_errors:>8,}")
    print(f"  wall clock         {elapsed:>8.2f}s   "
          f"({len(g.modules)/elapsed:,.0f} modules/sec)")

    if g.unresolved_reasons:
        print("  unbound because:")
        for reason, n in g.unresolved_reasons.most_common():
            print(f"    {n:>7,}  {reason}")

    if g.parse_errors:
        pct = g.parse_errors / len(g.modules)
        print(f"  NOTE: {pct:.1%} of files had parse errors; partial results kept")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    for arg in sys.argv[1:]:
        root = Path(arg)
        if not root.is_dir():
            print(f"skip {arg}: not a directory")
            continue
        bench(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
