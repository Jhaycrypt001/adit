"""`adit` -- the command line surface.

    adit trace [path]              full scan: ingest, bind, answer every advisory
    adit blast <pkg>@<version>     reverse transitive closure from an already-ingested release
    adit why <symbol-key>          explain a specific reachability result, including absence

`trace` is the product. `blast` and `why` exist because an incident is rarely a
single question -- once `trace` has ingested a repo, an engineer wants to follow
up without re-running the whole pipeline.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .graph import Edge, Hydra, Queries
from .render import render_report, to_json
from .scan import scan


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--bolt-uri", default=None, help="default: bolt://127.0.0.1:7687")
    p.add_argument("--token", default=None, help="default: local dev token")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--no-color", action="store_true")


def cmd_trace(args: argparse.Namespace) -> int:
    root = Path(args.path).resolve()
    if not root.is_dir():
        print(f"adit: {root} is not a directory", file=sys.stderr)
        return 2

    with Hydra(args.bolt_uri, args.token) as hydra:
        report = scan(root, hydra, max_len=args.max_len, allow_network=not args.offline)

    if args.json:
        print(json.dumps(to_json(report), indent=2))
    else:
        print(render_report(report, color=not args.no_color and sys.stdout.isatty()))

    # Exit non-zero when something is actionable, so `adit trace` composes in CI.
    return 1 if report.reachable else 0


def cmd_blast(args: argparse.Namespace) -> int:
    from .graph.ids import release_key

    try:
        name, version = args.spec.rsplit("@", 1)
    except ValueError:
        print("adit: expected <package>@<version>, e.g. lodash@4.17.20", file=sys.stderr)
        return 2

    with Hydra(args.bolt_uri, args.token) as hydra:
        q = Queries(hydra)
        target = release_key("npm", name, version)
        if not q.key_exists(target):
            print(f"adit: {args.spec} is not in the graph yet -- run `adit trace` first",
                  file=sys.stderr)
            return 2
        affected = q.blast_radius(target, rel=Edge.DEPENDS_ON, max_len=args.max_len)
        exposed = q.exposed_services(target)

    if args.json:
        print(json.dumps(
            {"package": args.spec, "blast_radius": affected, "exposed_services": exposed},
            indent=2,
        ))
        return 0

    print(f"{args.spec}")
    print(f"  {len(affected)} dependent package(s) within {args.max_len} hops")
    for dep in affected:
        print(f"    - {dep}")
    print(f"  {len(exposed)} service(s) resolved this exact version")
    for row in exposed:
        print(f"    - {row['service']}  (via {row['source']})")
    return 1 if (affected or exposed) else 0


def cmd_why(args: argparse.Namespace) -> int:
    with Hydra(args.bolt_uri, args.token) as hydra:
        q = Queries(hydra)
        if not q.key_exists(args.source):
            print(f"adit: {args.source} not found in the graph", file=sys.stderr)
            return 2
        if not q.key_exists(args.target):
            print(f"adit: {args.target} not found in the graph", file=sys.stderr)
            return 2

        result = q.reachability([args.source], [args.target], max_len=args.max_len)

    if args.json:
        print(json.dumps(
            {
                "reachable": result.reachable,
                "explanation": None if result.reachable else result.explain_absence(),
                "paths": [
                    [{"name": n.get("name"), "file": n.get("file"), "line": n.get("line")}
                     for n in p.nodes]
                    for p in result.paths
                ],
            },
            indent=2,
        ))
        return 0 if result.reachable else 1

    if not result.reachable:
        print(f"NOT REACHABLE: {result.explain_absence()}")
        return 1

    for path in result.paths:
        for depth, node in enumerate(path.nodes):
            where = f"{node.get('file', '?')}:{node.get('line', '?')}"
            arrow = "  " if depth == 0 else "-> "
            print(f"  {'  ' * depth}{arrow}{node.get('name', '?')}  ({where})")
        print()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="adit", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="command", required=True)

    trace = sub.add_parser("trace", help="scan a repository end to end")
    trace.add_argument("path", nargs="?", default=".")
    trace.add_argument("--max-len", type=int, default=12)
    trace.add_argument("--offline", action="store_true",
                        help="skip network calls that only refine symbol confidence (tier 2)")
    _add_common(trace)
    trace.set_defaults(func=cmd_trace)

    blast = sub.add_parser("blast", help="reverse transitive closure from a release")
    blast.add_argument("spec", help="package@version, e.g. keyv@5.5.4")
    blast.add_argument("--max-len", type=int, default=10)
    _add_common(blast)
    blast.set_defaults(func=cmd_blast)

    why = sub.add_parser("why", help="explain reachability between two symbol keys")
    why.add_argument("source")
    why.add_argument("target")
    why.add_argument("--max-len", type=int, default=12)
    _add_common(why)
    why.set_defaults(func=cmd_why)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="  %(levelname)s %(name)s: %(message)s",
    )
    try:
        return args.func(args)
    except FileNotFoundError as exc:
        print(f"adit: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
