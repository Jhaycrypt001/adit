"""HTTP surface for a browser-based frontend.

CLI, MCP, and this API all wrap the same three things: `scan()`, `Queries`,
and `render.to_json()`. None of them contain logic of their own -- a route
handler here is a JSON-in-JSON-out shim over a function already exercised by
`test_mcp_server.py`, so the payload shape is not speculative.

Neither the CLI (`adit trace --json` to stdout) nor the MCP server (stdio
RPC framing) is reachable from a browser's `fetch()`. This is the surface
that is -- nothing else in the project changes because it exists.

    adit-api                          uvicorn on 127.0.0.1:8420
    POST /scan       {"path": "..."}   -> the full report, as JSON
    GET  /blast/{pkg}@{version}        -> dependents + exposed services
    GET  /why?source=...&target=...    -> reachability explanation
    GET  /health                       -> HydraDB connectivity check

CORS is wide open (`allow_origins=["*"]`) on purpose: this binds to
127.0.0.1, is meant for local frontend development against a locally running
HydraDB, and carries no auth of its own -- the same trust boundary as the
CLI, which is "whoever can run this on your machine already has your repo
open." Don't expose this port beyond localhost without adding real auth.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .graph import Edge, Hydra, Queries
from .graph.ids import release_key
from .render import to_json
from .scan import scan

app = FastAPI(
    title="Adit",
    description="Reachability engine API -- see ARCHITECTURE.md for the query model.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _hydra() -> Hydra:
    return Hydra()


@app.get("/health")
def health() -> dict[str, Any]:
    """Is HydraDB actually reachable over Bolt right now?

    A frontend should call this before offering `/scan` -- a connection
    failure inside a POST is a worse first impression than a clear
    "database not running" state shown up front.
    """
    try:
        with _hydra() as h:
            h.run("MATCH (n {id: 1}) WHERE n.key = n.key RETURN n.key AS key")
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001 -- surfaced to the caller, not swallowed
        raise HTTPException(status_code=503, detail=f"HydraDB unreachable: {exc}") from None


class ScanRequest(BaseModel):
    path: str
    max_len: int = 12
    offline: bool = False


@app.post("/scan")
def scan_repo(req: ScanRequest) -> dict[str, Any]:
    """Ingest a repository and answer every dependency advisory.

    The expensive endpoint -- this is stages A through D plus every query,
    the same work `adit trace` does. Returns exactly what `render.to_json`
    returns; nothing is reshaped for HTTP, so the CLI's `--json` output and
    this response are byte-for-byte the same contract.
    """
    root = Path(req.path).resolve()
    if not root.is_dir():
        raise HTTPException(status_code=400, detail=f"{root} is not a directory")
    try:
        with _hydra() as hydra:
            report = scan(root, hydra, max_len=req.max_len, allow_network=not req.offline)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return to_json(report)


@app.get("/blast/{spec}")
def blast_radius(spec: str, max_len: int = 10) -> dict[str, Any]:
    """Reverse transitive closure and exposed services for `pkg@version`.

    Mirrors `adit blast` exactly, including the two-part answer: which
    packages transitively depend on the compromised release (the ecosystem
    question) and which of *your* services actually resolved that exact
    version, and when (the incident-response question) -- see
    `Queries.exposed_services` for why those are different questions.
    """
    try:
        name, version = spec.rsplit("@", 1)
    except ValueError:
        raise HTTPException(
            status_code=400, detail="expected <package>@<version>, e.g. lodash@4.17.20"
        ) from None

    with _hydra() as hydra:
        q = Queries(hydra)
        target = release_key("npm", name, version)
        if not q.key_exists(target):
            raise HTTPException(
                status_code=404,
                detail=f"{spec} is not in the graph yet -- POST /scan a repo that depends on it first",
            )
        return {
            "package": spec,
            "dependent_packages": q.blast_radius(target, rel=Edge.DEPENDS_ON, max_len=max_len),
            "exposed_services": q.exposed_services(target),
        }


@app.get("/why")
def why_reachable(
    source: str = Query(..., description="canonical symbol key, e.g. from a /scan result's paths"),
    target: str = Query(...),
    max_len: int = 12,
) -> dict[str, Any]:
    """Explain reachability between two exact symbol keys.

    Unlike the MCP server's `why_reachable` tool, this endpoint does not
    resolve bare names -- an HTTP client calling this already has exact keys
    from a prior `/scan` response's `paths`, and silently guessing at a name
    match over HTTP is a worse failure mode than requiring the caller to be
    precise. Use `/scan` first; its findings carry the keys this needs.
    """
    with _hydra() as hydra:
        q = Queries(hydra)
        if not q.key_exists(source):
            raise HTTPException(status_code=404, detail=f"{source} not found in the graph")
        if not q.key_exists(target):
            raise HTTPException(status_code=404, detail=f"{target} not found in the graph")

        result = q.reachability([source], [target], max_len=max_len)

    if not result.reachable:
        return {"reachable": False, "explanation": result.explain_absence()}
    path = result.shortest
    return {
        "reachable": True,
        "depth": path.depth,
        "path": [
            {"name": n.get("name"), "file": n.get("file"), "line": n.get("line")}
            for n in path.nodes
        ],
    }


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8420)


if __name__ == "__main__":
    main()
