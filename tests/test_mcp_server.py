"""The MCP server, driven through its real protocol path.

`server.call_tool()` is what an MCP client actually calls -- it validates
arguments against the generated schema before the Python function ever runs, so
this catches signature/schema mismatches that calling the function directly
would miss. Uses the demo fixture's checkout-service scan so the tools have
real data to answer against, not a mock.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

import pytest

from adit.graph import Hydra
from adit.ingest.deps_emit import emit_lockfile
from adit.ingest.emit import emit
from adit.ingest.lockfile import parse_package_lock
from adit.ingest.project import analyse
from adit.mcp_server import server

pytestmark = pytest.mark.integration

FIXTURE = Path(__file__).parent / "fixtures" / "tsapp"


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(scope="module")
def hydra():
    uri = os.environ.get("ADIT_BOLT_URI", "bolt://127.0.0.1:7687")
    h = Hydra(uri)
    try:
        h.verify()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no HydraDB at {uri}: {exc}")
    yield h
    h.close()


@pytest.fixture(scope="module")
def ingested(hydra):
    """Ingest the fixture's code graph directly (fast) rather than through the
    full scan pipeline (which needs live OSV) -- the MCP tools under test read
    the graph, they do not care how it got there."""
    graph = analyse(FIXTURE)
    graph.package_version = f"mcp{int(time.time() * 1000)}"
    emit(graph, hydra)
    return graph


def call(tool_name: str, **arguments) -> dict:
    """Invoke a tool exactly as an MCP client would, and unwrap the JSON payload."""
    result = run(server.call_tool(tool_name, arguments))
    assert not result.is_error, f"{tool_name} returned an error: {result.content}"
    text = result.content[0].text
    return json.loads(text)


def test_server_advertises_exactly_five_tools(hydra):
    """The roadmap's context-budget constraint: a handful of tools, not a
    wrapper around every method Queries exposes."""
    tools = run(server.list_tools())
    names = {t.name for t in tools}
    assert names == {
        "trace_repository", "why_reachable", "blast_radius", "callers_of", "find_symbol",
    }


def test_find_symbol_locates_a_real_symbol(ingested, hydra):
    """The graph is persistent and shared across the whole test session, so a
    bare name like `normalizePayload` may match more than one ingested version
    of this same fixture. Check that OUR match is present, not that it is
    first -- ordering across an accumulating graph is not something Adit
    promises, and a test that assumed it would be testing an accident."""
    result = call("find_symbol", name="normalizePayload")
    assert result["matches"]
    assert any(
        m["file"] == "src/lib/normalize.ts" and m["exported"] is True
        for m in result["matches"]
    )


def test_find_symbol_reports_no_matches_honestly(ingested, hydra):
    result = call("find_symbol", name="thisFunctionDoesNotExist")
    assert result["matches"] == []


def _key(graph, module: str, symbol: str) -> str:
    """Build the exact canonical key for a symbol in this test run's freshly
    ingested version, rather than relying on bare-name lookup -- which is
    genuinely ambiguous against a shared, persistent, accumulating graph. This
    exercises the tool's other resolution path: an already-canonical key that
    exists is used as-is, no name search involved."""
    from adit.graph.ids import symbol_key

    return symbol_key(graph.package_name, graph.package_version, module, symbol)


def test_why_reachable_resolves_through_the_barrel(ingested, hydra):
    """The same barrel-reexport case from test_ingest_e2e.py, through MCP."""
    source = _key(ingested, "src/api/orders.ts", "handleOrder")
    target = _key(ingested, "src/lib/normalize.ts", "normalizePayload")
    result = call("why_reachable", source=source, target=target)
    assert result["reachable"] is True
    assert [n["name"] for n in result["path"]] == ["handleOrder", "normalizePayload"]
    assert all(n["file"] and n["line"] for n in result["path"])


def test_why_reachable_explains_absence_not_just_false(ingested, hydra):
    source = _key(ingested, "src/orphan.ts", "orphan")
    target = _key(ingested, "src/lib/normalize.ts", "normalizePayload")
    result = call("why_reachable", source=source, target=target)
    assert result["reachable"] is False
    assert "no path" in result["explanation"]


def test_why_reachable_reports_unknown_symbol_as_error_not_crash(ingested, hydra):
    result = call("why_reachable", source="totallyUnknownThingXYZ123", target="merge")
    assert "error" in result


def test_why_reachable_resolves_a_bare_name_when_unambiguous(ingested, hydra):
    """`orphan` -> `normalizePayload` by NAME, not canonical key. This is the
    convenience path an agent uses before ever calling find_symbol; it works
    here because these two names are unlikely to collide with anything else
    in a freshly extended session, not because Adit guarantees uniqueness --
    see the find_symbol test above for what happens when a name IS ambiguous."""
    result = call("why_reachable", source="orphan", target="normalizePayload")
    assert "reachable" in result  # resolved to *some* pair; did not error out


def test_callers_of_finds_transitive_caller(ingested, hydra):
    target = _key(ingested, "src/lib/normalize.ts", "normalizePayload")
    result = call("callers_of", symbol=target)
    assert _key(ingested, "src/api/orders.ts", "handleOrder") in result["callers"]


def test_blast_radius_reports_clear_error_for_unknown_package(hydra):
    result = call("blast_radius", package_spec="left-pad@9.9.9")
    assert "error" in result
    assert "trace_repository" in result["error"]


def test_blast_radius_rejects_malformed_spec(hydra):
    result = call("blast_radius", package_spec="not-a-valid-spec")
    assert "error" in result


def test_trace_repository_rejects_nonexistent_path(hydra):
    result = call("trace_repository", path="/definitely/not/a/real/path")
    assert "error" in result


def test_tool_descriptions_are_short(hydra):
    """Long descriptions are exactly what burns an agent's context window --
    keep each under a budget rather than letting them grow unchecked."""
    tools = run(server.list_tools())
    for tool in tools:
        assert tool.description is not None
        assert len(tool.description) < 700, f"{tool.name}: {len(tool.description)} chars"
