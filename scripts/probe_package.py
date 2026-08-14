"""Can Adit find a named export inside a real npm package, and reach it?

This is the stage D acceptance test in miniature. Everything the product claims
rests on it: if we cannot locate lodash's `merge` in lodash's own source, and
follow its internal calls, then "reachability" has nowhere to land and the tool
degrades to package-level alerting.

    py scripts/probe_package.py <node_modules/pkg> <exported-name>
"""

from __future__ import annotations

import sys
from pathlib import Path

from adit.ingest.project import analyse


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    root, wanted = Path(sys.argv[1]), sys.argv[2]

    graph = analyse(root)
    print(f"{root.name}: {graph.summary()}\n")

    # Where is the wanted name declared?
    declarations = [
        (path, s.name, s.kind, s.line, s.exported)
        for path, info in graph.modules.items()
        for s in info.symbols.values()
        if s.name == wanted
    ]
    print(f"declarations of {wanted!r}: {len(declarations)}")
    for path, name, kind, line, exported in declarations[:6]:
        flag = "exported" if exported else "internal"
        print(f"  {path}:{line}  {kind:<9} {flag}")

    # Is it reachable as an export from the module named after it?
    from adit.ingest.project import Resolver

    resolver = Resolver(graph.modules, root)
    entry = f"{wanted}.js"
    if entry in graph.modules:
        hit = resolver.resolve_export(entry, wanted)
        print(f"\nresolve_export({entry!r}, {wanted!r}) -> {hit}")
        hit_default = resolver.resolve_export(entry, "default")
        print(f"resolve_export({entry!r}, 'default')  -> {hit_default}")

    # What does it call? This is the chain reachability will traverse.
    outgoing = [
        (tm, ts) for (m, s, tm, ts) in graph.internal_calls if s == wanted
    ]
    print(f"\n{wanted} calls {len(outgoing)} internal target(s):")
    for tm, ts in outgoing[:10]:
        print(f"  -> {ts}  ({tm})")

    # And who calls it -- the backward slice inside the package.
    incoming = {s for (_, s, _, ts) in graph.internal_calls if ts == wanted}
    print(f"\ncalled by {len(incoming)} symbol(s) inside the package")

    ok = bool(declarations) and bool(outgoing)
    print(f"\n{'PASS' if ok else 'FAIL'}: symbol {'found and traversable' if ok else 'not usable'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
