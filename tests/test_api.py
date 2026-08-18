"""The HTTP surface, exercised the way a browser frontend actually would --
through FastAPI's TestClient, not by calling the route functions directly.

Every route here is a thin shim over `scan()` / `Queries` / `render.to_json`,
already covered by test_ingest_e2e.py, test_deps_e2e.py and test_mcp_server.py.
What's specific to THIS surface: HTTP status codes on the error paths, CORS,
the SSRF/rate-limit boundaries that only exist because this is meant to be
reachable from the public internet (see api.py's module docstring), and one
real end-to-end proof that clone -> install --ignore-scripts -> scan works
together over actual HTTP, not just as separately-tested pieces.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

import adit.api as api_module
from adit.api import app
from adit.graph import Hydra

FIXTURE_REPO = "https://github.com/octocat/Hello-World"  # no package.json -- error-path fixture


@pytest.fixture
def client():
    """Fresh TestClient AND a fresh rate-limit table per test -- the limiter
    is a module-level dict so tests would otherwise interfere with each
    other's quota."""
    api_module._scan_history.clear()
    return TestClient(app)


def _hydra_reachable() -> bool:
    uri = os.environ.get("ADIT_BOLT_URI", "bolt://127.0.0.1:7687")
    try:
        Hydra(uri).verify()
        return True
    except Exception:  # noqa: BLE001
        return False


# -- offline: error paths, shape, security boundaries ------------------------


def test_blast_rejects_malformed_spec(client):
    resp = client.get("/blast/not-a-valid-spec")
    assert resp.status_code == 400
    assert "<package>@<version>" in resp.json()["detail"]


def test_scan_rejects_a_non_github_url():
    """The SSRF boundary, at the HTTP layer -- test_remote.py already proves
    validate_github_url() itself is thorough; this proves api.py actually
    calls it and turns the rejection into a clean 400, not a 500."""
    client = TestClient(app)
    resp = client.post("/scan", json={"repo_url": "https://169.254.169.254/"})
    assert resp.status_code == 400


def test_scan_rejects_a_local_filesystem_path():
    """The old contract is gone -- a bare path is not a valid repo_url and
    must fail validation, not silently resolve on the server's filesystem."""
    client = TestClient(app)
    resp = client.post("/scan", json={"repo_url": "/etc/passwd"})
    assert resp.status_code == 400


def test_scan_rejects_max_len_past_the_ceiling():
    client = TestClient(app)
    resp = client.post(
        "/scan", json={"repo_url": "https://github.com/a/b", "max_len": 9999}
    )
    assert resp.status_code == 422  # pydantic's own Field(le=...) validation


def test_why_requires_both_query_params(client):
    resp = client.get("/why", params={"source": "sym:x#a"})
    assert resp.status_code == 422  # FastAPI's own validation, target missing


def test_cors_is_open_for_a_frontend(client):
    resp = client.options(
        "/health",
        headers={
            "Origin": "https://adit.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.headers.get("access-control-allow-origin") == "*"


def test_scan_rate_limit_kicks_in_after_the_window(client):
    """Doesn't need a real clone -- an invalid URL is rejected (400) well
    before the rate limiter would matter for a REAL scan, but the limiter
    itself runs before validation, so this proves the boundary independent
    of whether any individual request would have succeeded."""
    url = "https://169.254.169.254/"  # deliberately invalid; every call 400s
    for _ in range(5):
        resp = client.post("/scan", json={"repo_url": url})
        assert resp.status_code == 400
    resp = client.post("/scan", json={"repo_url": url})
    assert resp.status_code == 429
    assert "rate limit" in resp.json()["detail"]


# -- integration: needs a live HydraDB ---------------------------------------


@pytest.mark.integration
def test_health_reports_ok_when_hydradb_is_up(client):
    if not _hydra_reachable():
        pytest.skip("no HydraDB reachable")
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


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


@pytest.mark.integration
def test_scan_repo_with_no_package_json_is_a_clean_400(client):
    """octocat/Hello-World has no package.json/lockfile at all -- confirms
    the clone -> install -> scan pipeline fails cleanly at the right stage
    instead of a stack trace, for a repo that is real but not npm at all."""
    if not _hydra_reachable():
        pytest.skip("no HydraDB reachable")
    resp = client.post("/scan", json={"repo_url": FIXTURE_REPO})
    assert resp.status_code in (400, 422)


@pytest.mark.integration
@pytest.mark.slow
def test_full_hosted_pipeline_end_to_end_over_real_http(client):
    """The whole point: clone (real network) -> npm install --ignore-scripts
    (real network, real dependency resolution) -> scan (real OSV queries,
    real graph writes) -> the response a browser would actually receive,
    for a repo we already know the correct answer for (see the express
    case study in README.md) -- proving the NEW hosted code path reaches
    the SAME known-correct result the CLI does, not a parallel
    implementation that could silently drift.
    """
    if not _hydra_reachable():
        pytest.skip("no HydraDB reachable")

    # No explicit timeout: TestClient drives the app in-process over ASGI,
    # not a real socket, so a request-level timeout kwarg is deprecated on it
    # -- the slowness here is git clone / npm install, which already carry
    # their own timeouts inside remote.py.
    resp = client.post(
        "/scan",
        json={"repo_url": "https://github.com/expressjs/express"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert "scan_id" in body and body["scan_id"]
    assert body["package"].startswith("express@")
    # The known-correct result, reached this time through git clone + a real
    # npm install rather than a pre-existing local checkout.
    assert all(not f["actionable"] for f in body["findings"]), (
        "express's real vulnerabilities all live in dev tooling (mocha/nyc) "
        "and were previously confirmed unreachable -- a change here means "
        "either a real regression or express's own dependencies changed"
    )

    # A follow-up /blast scoped to this scan_id must not error even if the
    # package in question was never part of this repo's dependency tree --
    # 404 is a correct, quiet "not found", not a 500.
    follow_up = client.get(
        "/blast/left-pad-definitely-not-a-real-dep@0.0.0",
        params={"scan_id": body["scan_id"]},
    )
    assert follow_up.status_code == 404
