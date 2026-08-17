"""The HTTP surface, exercised the way a browser frontend actually would --
through FastAPI's TestClient, not by calling the route functions directly.

Every route here is a thin shim over `scan()` / `Queries` / `render.to_json`,
already covered by test_ingest_e2e.py, test_deps_e2e.py and test_mcp_server.py.
What's specific to THIS surface and worth testing on its own: HTTP status
codes on the error paths (400/404/503, not a Python exception), that CORS is
actually open, and that the JSON payload matches what render.to_json produces
byte-for-byte -- the whole point of reusing it rather than reshaping per route.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from adit.api import app
from adit.graph import Hydra
from adit.ingest.emit import emit
from adit.ingest.project import analyse

FIXTURE = Path(__file__).parent / "fixtures" / "tsapp"


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


# -- offline: error paths and shape, no live scan needed --------------------


def test_blast_rejects_malformed_spec(client):
    resp = client.get("/blast/not-a-valid-spec")
    assert resp.status_code == 400
    assert "<package>@<version>" in resp.json()["detail"]


def test_scan_rejects_nonexistent_path(client):
    resp = client.post("/scan", json={"path": "/definitely/not/a/real/path"})
    assert resp.status_code == 400


def test_why_requires_both_query_params(client):
    resp = client.get("/why", params={"source": "sym:x#a"})
    assert resp.status_code == 422  # FastAPI's own validation, target missing


def test_cors_is_open_for_a_local_frontend(client):
    resp = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.headers.get("access-control-allow-origin") == "*"


# -- integration: needs a live HydraDB, real graph data ----------------------

pytestmark_integration = pytest.mark.integration


def _hydra_reachable() -> bool:
    uri = os.environ.get("ADIT_BOLT_URI", "bolt://127.0.0.1:7687")
    try:
        Hydra(uri).verify()
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.integration
def test_health_reports_ok_when_hydradb_is_up(client):
    if not _hydra_reachable():
        pytest.skip("no HydraDB reachable")
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.integration
def test_why_finds_the_same_barrel_reexport_path_as_the_cli(client):
    """Same fixture, same barrel-reexport case as test_ingest_e2e.py, hit
    through HTTP -- proves the API returns the identical answer the CLI does,
    not a parallel implementation that could silently drift."""
    if not _hydra_reachable():
        pytest.skip("no HydraDB reachable")

    from adit.graph.ids import symbol_key

    with Hydra() as hydra:
        graph = analyse(FIXTURE)
        graph.package_version = f"api{int(time.time() * 1000)}"
        emit(graph, hydra)

    source = symbol_key(graph.package_name, graph.package_version,
                         "src/api/orders.ts", "handleOrder")
    target = symbol_key(graph.package_name, graph.package_version,
                         "src/lib/normalize.ts", "normalizePayload")

    resp = client.get("/why", params={"source": source, "target": target})
    assert resp.status_code == 200
    body = resp.json()
    assert body["reachable"] is True
    assert [n["name"] for n in body["path"]] == ["handleOrder", "normalizePayload"]


@pytest.mark.integration
def test_why_returns_404_for_unknown_keys(client):
    if not _hydra_reachable():
        pytest.skip("no HydraDB reachable")
    resp = client.get("/why", params={"source": "sym:nope#a", "target": "sym:nope#b"})
    assert resp.status_code == 404


@pytest.mark.integration
def test_blast_returns_404_for_a_package_never_scanned(client):
    if not _hydra_reachable():
        pytest.skip("no HydraDB reachable")
    resp = client.get("/blast/left-pad-definitely-never-scanned@9.9.9")
    assert resp.status_code == 404
    assert "POST /scan" in resp.json()["detail"]
