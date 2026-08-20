"""Turn a ScanReport into the output a human reads.

One rule drives every choice here: never claim more certainty than the data
supports. A tier-3 symbol guess is never printed the way a tier-1 fact is; an
install-time finding is never shown a "reachable" path, because reachability
was never the question for it.
"""

from __future__ import annotations

from .graph.schema import AdvisoryClass
from .scan import Finding, ScanReport, Status

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
CYAN = "\033[36m"


def _c(code: str, text: str, *, color: bool) -> str:
    return f"{code}{text}{RESET}" if color else text


def render_finding(f: Finding, *, color: bool = True, max_paths: int = 2) -> str:
    lines: list[str] = []
    if f.klass is AdvisoryClass.INSTALL_TIME:
        mark, tint = "!", RED
    elif f.status is Status.UNRESOLVED:
        # Deliberately not the same glyph as a confirmed path: this row means
        # "Adit could not determine the vulnerable symbol", not "Adit searched
        # and found a route to it". Collapsing the two would claim a search
        # that never ran -- see scan.py's Status docstring.
        mark, tint = "?", CYAN
    else:
        mark, tint = "x", YELLOW

    header = f"{mark} {f.advisory.id}  {f.package.spec}  [{f.klass.value}]"
    lines.append(_c(tint, header, color=color))
    lines.append(f"    {f.advisory.summary[:96]}")

    if f.resolution is not None:
        conf_tag = f"tier {f.resolution.tier}, confidence {f.resolution.confidence}"
        lines.append(_c(DIM, f"    symbol: {f.resolution.describe()[:96]}  ({conf_tag})", color=color))

    if f.klass is AdvisoryClass.INSTALL_TIME:
        lines.append(f"    {f.reason}")
        if f.blast:
            lines.append(f"    blast radius: {len(f.blast)} dependent(s)")
            for dep in f.blast[:6]:
                lines.append(f"      - {dep}")
            if len(f.blast) > 6:
                lines.append(f"      ... and {len(f.blast) - 6} more")
        return "\n".join(lines)

    if f.status is Status.UNRESOLVED:
        lines.append(_c(CYAN, f"    {f.reason}", color=color))
        return "\n".join(lines)

    for path in f.paths[:max_paths]:
        lines.append("    path:")
        for depth, node in enumerate(path.nodes):
            where = f"{node.get('file', '?')}:{node.get('line', '?')}"
            arrow = "  " if depth == 0 else "-> "
            is_last = depth == len(path.nodes) - 1
            name = node.get("name", "?")
            tail = _c(RED, "   <- vulnerable", color=color) if is_last else ""
            indent = "  " * depth
            lines.append(f"      {indent}{arrow}{name}  ({where}){tail}")
    return "\n".join(lines)


def render_not_reachable(f: Finding, *, color: bool = True) -> str:
    return _c(DIM, f"    - {f.advisory.id}  {f.package.spec}  ({f.reason[:76]})", color=color)


def render_report(report: ScanReport, *, color: bool = True, max_paths: int = 2) -> str:
    lines: list[str] = []
    lines.append(_c(BOLD, f"{report.repo.package_name}@{report.repo.package_version}", color=color)
                 + f"   {report.root}")
    lines.append(f"  {report.repo.summary()}")
    lines.append(f"  {report.lock.summary()}")
    if report.bind_result:
        lines.append(f"  {report.bind_result.summary()}")
    lines.append("")

    hot, cold = report.reachable, report.not_reachable
    unresolved = sum(1 for f in hot if f.status is Status.UNRESOLVED)
    lines.append(_c(BOLD, f"  {len(report.findings)} advisories affecting this repo", color=color))
    tail = f"  ({unresolved} unresolved -- symbol not located, not checked)" if unresolved else ""
    lines.append(_c(RED if hot else GREEN, f"  {len(hot)} ACTIONABLE", color=color) + tail)
    lines.append(f"  {len(cold)} not reachable")
    lines.append("")

    for f in hot:
        lines.append(render_finding(f, color=color, max_paths=max_paths))
        lines.append("")

    if cold:
        lines.append(_c(DIM, "  not reachable:", color=color))
        for f in cold:
            lines.append(render_not_reachable(f, color=color))
        lines.append("")

    timing = ", ".join(f"{k} {v:.2f}s" for k, v in report.timings.items())
    lines.append(_c(DIM, f"  timings: {timing}", color=color))
    lines.append(_c(DIM, f"  total {report.elapsed:.2f}s", color=color))
    return "\n".join(lines)


def to_json(report: ScanReport) -> dict:
    """Structured form for the MCP server and any future frontend.

    Kept alongside the text renderer rather than as an afterthought, so the two
    surfaces can never silently disagree about what a finding contains.
    """
    def finding(f: Finding) -> dict:
        return {
            "advisory_id": f.advisory.id,
            "summary": f.advisory.summary,
            "severity": f.advisory.severity,
            "class": f.klass.value,
            "package": f.package.spec,
            "actionable": f.actionable,
            "status": f.status.value,
            "reachable": f.reachable,
            "reason": f.reason,
            "symbol": (
                {
                    "names": f.resolution.symbols,
                    "tier": f.resolution.tier,
                    "confidence": f.resolution.confidence,
                    "method": f.resolution.method,
                }
                if f.resolution
                else None
            ),
            # `key` is projected deliberately. Without it a client could render
            # a path but not ask a follow-up question about any node in it:
            # /why takes exact canonical keys and refuses to guess at bare
            # names, so a UI built on this payload had no way to obtain the one
            # input that endpoint accepts. Name/file/line are for display; key
            # is the identity the rest of the API is addressed by.
            "paths": [
                [
                    {
                        "key": n.get("key"),
                        "name": n.get("name"),
                        "file": n.get("file"),
                        "line": n.get("line"),
                    }
                    for n in p.nodes
                ]
                for p in f.paths
            ],
            "blast_radius": f.blast,
        }

    return {
        "package": f"{report.repo.package_name}@{report.repo.package_version}",
        "root": str(report.root),
        "headline": report.headline(),
        "findings": [finding(f) for f in report.findings],
        "timings": report.timings,
        "elapsed": report.elapsed,
    }
