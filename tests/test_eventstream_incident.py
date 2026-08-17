"""The install-time story, proven against the real 2018 event-stream incident
-- not a synthetic scenario.

`npm install event-stream@3.3.6` fails today with ETARGET: npm unpublished the
compromised release as part of the actual incident response, so it can no
longer be freshly installed. That is itself the point this test makes: a real
2018 incident responder could not "just reinstall" the bad version to check
exposure -- they had to check what their OWN existing lockfile had already
resolved. This is why Adit checks history rather than re-fetching artifacts.

The lockfile below is reconstructed (npm can no longer generate a real one for
this release), using the real published/pulled dates from public incident
writeups -- flatmap-stream 0.1.1 was published 2018-09-08 and pulled
2018-11-20. Everything downstream of the lockfile -- the OSV query, the
install-time classification, blast radius, and the temporal window check --
runs through the exact same `emit_lockfile()` / `Queries` code every other
scan in this project uses. No demo-only code path.
"""

from __future__ import annotations

import os
import time

import pytest

from adit.graph import Hydra, Queries
from adit.graph.ids import release_key
from adit.graph.schema import AdvisoryClass
from adit.ingest.deps_emit import emit_lockfile
from adit.ingest.lockfile import LockGraph, ResolvedPackage
from adit.ingest.osv import OsvClient, classify

pytestmark = pytest.mark.integration

# Real dates, from public writeups of the incident.
PUBLISHED = int(time.mktime((2018, 9, 8, 0, 0, 0, 0, 0, 0)))
PULLED = int(time.mktime((2018, 11, 20, 0, 0, 0, 0, 0, 0)))
RESOLVED_AT = PUBLISHED + 86400 * 10  # this lockfile resolved it 10 days after publish


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
    run = f"t{int(time.time() * 1000)}"
    service = f"log-pipeline-{run}"
    lock = LockGraph(
        root_name=service, root_version="1.0.0",
        lockfile="package-lock.json", lockfile_version=2,
        packages={
            "node_modules/event-stream": ResolvedPackage(
                name="event-stream", version="3.3.6", path="node_modules/event-stream",
            ),
            "node_modules/event-stream/node_modules/flatmap-stream": ResolvedPackage(
                name="flatmap-stream", version="0.1.1",
                path="node_modules/event-stream/node_modules/flatmap-stream",
            ),
        },
        direct={"event-stream"},
    )
    lock.edges = [
        ("", "node_modules/event-stream"),
        ("node_modules/event-stream", "node_modules/event-stream/node_modules/flatmap-stream"),
    ]
    emit_lockfile(
        lock, hydra, service_name=service, observed_at=RESOLVED_AT,
        source="package-lock.json (reconstructed, 2018 incident)",
    )
    return service


@pytest.fixture(scope="module")
def real_advisories():
    with OsvClient() as osv:
        hits = osv.query_batch([("flatmap-stream", "0.1.1")])
        ids = [i for group in hits.values() for i in group]
        return osv.fetch_many(ids)


def test_npm_no_longer_serves_the_compromised_release():
    """Documents WHY the lockfile is reconstructed rather than installed --
    if this ever starts passing, npm re-published the malicious release,
    which would itself be newsworthy."""
    import httpx

    resp = httpx.get("https://registry.npmjs.org/flatmap-stream/0.1.1", timeout=15)
    assert resp.status_code == 404, (
        "flatmap-stream@0.1.1 is unexpectedly available again on the npm registry"
    )


def test_real_osv_carries_a_malicious_package_entry(real_advisories):
    assert any(a.id.startswith("MAL-") for a in real_advisories.values()), (
        "OSV's malicious-package database no longer lists this incident"
    )


def test_malicious_entry_classifies_install_time(real_advisories):
    mal = next(a for a in real_advisories.values() if a.id.startswith("MAL-"))
    assert classify(mal) is AdvisoryClass.INSTALL_TIME


def test_blast_radius_includes_the_real_dependent_chain(ingested, hydra):
    q = Queries(hydra)
    target = release_key("npm", "flatmap-stream", "0.1.1")
    affected = q.blast_radius(target)
    assert release_key("npm", "event-stream", "3.3.6") in affected
    assert release_key("npm", ingested, "1.0.0") in affected


def test_service_is_exposed_during_the_real_live_window(ingested, hydra):
    q = Queries(hydra)
    target = release_key("npm", "flatmap-stream", "0.1.1")
    exposed = q.exposed_services(target, PUBLISHED, PULLED)
    assert any(row["service"].endswith(ingested) for row in exposed)
    assert exposed[0]["source"] == "package-lock.json (reconstructed, 2018 incident)"


def test_service_is_not_exposed_before_the_compromise_existed(ingested, hydra):
    """The temporal abstention, on real dates: nothing resolved a fact before
    that fact was true. Getting this wrong would mean Adit can fabricate
    exposure that never happened."""
    q = Queries(hydra)
    target = release_key("npm", "flatmap-stream", "0.1.1")
    before_2017 = int(time.mktime((2017, 1, 1, 0, 0, 0, 0, 0, 0)))
    before_2017_end = int(time.mktime((2017, 12, 31, 0, 0, 0, 0, 0, 0)))
    assert q.exposed_services(target, before_2017, before_2017_end) == []
