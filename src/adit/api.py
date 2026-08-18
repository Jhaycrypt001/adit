"""HTTP surface for a browser-based frontend, designed to be safe to expose
to the public internet -- not just to localhost.

CLI, MCP, and this API all wrap the same three things: `scan()`, `Queries`,
and `render.to_json()`. None of them contain logic of their own -- a route
handler here is a JSON-in-JSON-out shim over a function already exercised by
`test_mcp_server.py`, so the payload shape is not speculative.

    adit-api                              uvicorn on 0.0.0.0:8420
    POST /scan   {"repo_url": "https://github.com/owner/repo"}
                                           -> the full report, as JSON,
                                              plus a scan_id for follow-ups
    GET  /blast/{pkg}@{version}?scan_id=...
    GET  /why?source=...&target=...&scan_id=...
    GET  /health

## Why this doesn't take a filesystem path anymore

It used to: `POST /scan {"path": "..."}`, resolved on the server. That is
fine for a CLI (same trust boundary as running any command on your own
machine) and an arbitrary-file-read vulnerability the moment this endpoint is
reachable from the internet, since the path is resolved on the *server*, not
whoever sent the request. `remote.cloned_repo()` replaces it: a client names
a `github.com` URL, the server clones it into an isolated temp directory
nothing else can guess, and the directory is always removed afterward --
`InvalidRepoUrl`/`CloneFailed` map to clean 4xx responses, not a stack trace.

## Multi-tenant isolation, honestly described

HydraDB rejects any graph-database name it wasn't started with (confirmed
live: `session(database="x")` fails with "unknown graph database"), so
per-request engine-level databases are not an option this engine offers.
Isolation instead happens through `graph.ids.scan_scope()`: every scan's ids
are hashed with a random namespace folded in, so two scans of the identical
repo cannot collide, and nothing outside a scan's own response ever learns
its namespace -- discoverability is what's prevented, not persistence; the
data is not deleted, HydraDB has no expiry mechanism, and that is a known,
stated limitation rather than a claim this file doesn't make.

## Trust boundary

No auth beyond an in-memory per-IP rate limit on the one expensive,
abuse-prone endpoint (`/scan`, since it clones a repo, calls OSV, and runs
the full pipeline). Good enough for a hackathon-timeline hosted demo; a real
multi-instance production deployment needs a shared rate-limit store (Redis
or similar) instead of a process-local dict, and probably real accounts.
Said here rather than left implicit.
"""

from __future__ import annotations

import time
from collections import defaultdict
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .graph import Edge, Hydra, Queries
from .graph.ids import release_key, scan_scope
from .remote import CloneFailed, DependencyInstallFailed, InvalidRepoUrl, cloned_repo, install_dependencies
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

#: A traversal depth past this is not a realistic call chain, and letting a
#: client request an unbounded one is a cheap way to make MSpaths do
#: needless work -- capped the same way on every endpoint that takes it.
MAX_LEN_CEILING = 30

_SCAN_WINDOW_SECONDS = 600
_SCAN_LIMIT_PER_WINDOW = 5
_scan_history: dict[str, list[float]] = defaultdict(list)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _check_scan_rate_limit(request: Request) -> None:
    """5 scans per 10 minutes per client IP.

    In-memory and process-local on purpose for now -- see the module
    docstring's Trust boundary section for what that does and doesn't cover.
    """
    ip = _client_ip(request)
    now = time.monotonic()
    history = _scan_history[ip]
    history[:] = [t for t in history if now - t < _SCAN_WINDOW_SECONDS]
    if len(history) >= _SCAN_LIMIT_PER_WINDOW:
        raise HTTPException(
            status_code=429,
            detail=f"rate limit: max {_SCAN_LIMIT_PER_WINDOW} scans per "
            f"{_SCAN_WINDOW_SECONDS // 60} minutes per client",
        )
    history.append(now)


def _hydra() -> Hydra:
    return Hydra()


def _namespace_for(scan_id: str) -> str:
    return f"scan-{scan_id}"


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
    repo_url: str = Field(
        ..., description="A public https://github.com/<owner>/<repo> URL."
    )
    max_len: int = Field(12, ge=1, le=MAX_LEN_CEILING)
    offline: bool = False


@app.post("/scan")
def scan_repo(req: ScanRequest, request: Request) -> dict[str, Any]:
    """Clone a public GitHub repo and answer every dependency advisory.

    The expensive, abuse-prone endpoint -- rate limited. Ingests into an
    isolated id namespace unique to this request (`scan_id`, returned in the
    response) so concurrent scans by different clients cannot collide or see
    each other's data; pass that `scan_id` back to `/blast` or `/why` to ask
    a follow-up question about this same scan.
    """
    _check_scan_rate_limit(request)

    scan_id = uuid4().hex
    try:
        with cloned_repo(req.repo_url) as root:
            install_dependencies(root)
            with scan_scope(_namespace_for(scan_id)), _hydra() as hydra:
                report = scan(
                    Path(root), hydra, max_len=req.max_len, allow_network=not req.offline
                )
    except InvalidRepoUrl as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except CloneFailed as exc:
        raise HTTPException(status_code=422, detail=f"could not clone: {exc}") from None
    except DependencyInstallFailed as exc:
        raise HTTPException(
            status_code=422, detail=f"could not install dependencies: {exc}"
        ) from None
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    body = to_json(report)
    body["scan_id"] = scan_id
    return body


@app.get("/blast/{spec}")
def blast_radius(
    spec: str,
    max_len: int = Query(10, ge=1, le=MAX_LEN_CEILING),
    scan_id: str | None = None,
) -> dict[str, Any]:
    """Reverse transitive closure and exposed services for `pkg@version`.

    Mirrors `adit blast`. Pass the `scan_id` a prior `/scan` returned to ask
    about that scan's own data; omitted, this queries the shared unscoped
    namespace (empty on a purely hosted deployment where every write goes
    through `/scan`'s per-request scope, but present if the CLI has been
    pointed at the same HydraDB instance during local development).
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

        def _query() -> dict[str, Any] | None:
            if not q.key_exists(target):
                return None
            return {
                "package": spec,
                "dependent_packages": q.blast_radius(
                    target, rel=Edge.DEPENDS_ON, max_len=max_len
                ),
                "exposed_services": q.exposed_services(target),
            }

        if scan_id is not None:
            with scan_scope(_namespace_for(scan_id)):
                result = _query()
        else:
            result = _query()

    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"{spec} is not in the graph yet -- POST /scan a repo that depends on it first",
        )
    return result


@app.get("/why")
def why_reachable(
    source: str = Query(..., description="canonical symbol key, e.g. from a /scan result's paths"),
    target: str = Query(...),
    max_len: int = Query(12, ge=1, le=MAX_LEN_CEILING),
    scan_id: str | None = None,
) -> dict[str, Any]:
    """Explain reachability between two exact symbol keys.

    Unlike the MCP server's `why_reachable` tool, this endpoint does not
    resolve bare names -- an HTTP client calling this already has exact keys
    from a prior `/scan` response's `paths`, and silently guessing at a name
    match over a public HTTP surface is a worse failure mode than requiring
    the caller to be precise. Pass the same `scan_id` that `/scan` returned.
    """

    def _query() -> dict[str, Any]:
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

    if scan_id is not None:
        with scan_scope(_namespace_for(scan_id)):
            return _query()
    return _query()


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8420)  # noqa: S104 -- intended for hosted deployment


if __name__ == "__main__":
    main()
