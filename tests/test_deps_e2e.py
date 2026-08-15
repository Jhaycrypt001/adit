"""Stage B end to end: lockfile -> HydraDB -> blast radius and exposed services.

The gap this closes: `lockfile.load()` parsed a dependency graph that nothing
ever wrote to the database, so `adit blast` always returned zero -- silently,
which is worse than an error. These assertions pin the two questions an
incident actually needs answered:

    "what depends on the compromised package"      -- blast_radius (ecosystem)
    "which of my services resolved it, and when"    -- exposed_services (mine)
"""

from __future__ import annotations

import json
import os
import time

import pytest

from adit.graph import Edge, Hydra, Queries
from adit.graph.ids import release_key
from adit.ingest.deps_emit import emit_lockfile
from adit.ingest.lockfile import parse_package_lock

pytestmark = pytest.mark.integration

# service -> app -> shared -> BAD (compromised, transitive)
#        \-> other (unrelated dependent of BAD's sibling, must not appear)
LOCK = {
    "name": "checkout",
    "version": "1.0.0",
    "lockfileVersion": 3,
    "packages": {
        "": {"name": "checkout", "version": "1.0.0", "dependencies": {"app": "^1"}},
        "node_modules/app": {"version": "1.0.0", "dependencies": {"shared": "^1"}},
        "node_modules/shared": {"version": "1.0.0", "dependencies": {"bad": "^1"}},
        "node_modules/bad": {"version": "1.0.0"},
        "node_modules/other": {"version": "1.0.0", "dependencies": {"unrelated": "^1"}},
        "node_modules/unrelated": {"version": "1.0.0"},
    },
}


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
def loaded(hydra, tmp_path_factory):
    run = f"t{int(time.time() * 1000)}"
    lock_data = json.loads(json.dumps(LOCK))
    lock_data["name"] = f"checkout-{run}"  # namespace so parallel test runs never collide
    for meta in lock_data["packages"].values():
        if "name" in meta:
            meta["name"] = lock_data["name"]

    path = tmp_path_factory.mktemp("lockfixture") / "package-lock.json"
    path.write_text(json.dumps(lock_data), encoding="utf-8")
    lock = parse_package_lock(path)

    emit_lockfile(lock, hydra, service_name=lock.root_name, observed_at=1_000, source="test")
    return lock, run


def rk(run: str, name: str) -> str:
    return release_key("npm", name, "1.0.0")


# -- blast radius: the ecosystem question -----------------------------------


def test_blast_radius_finds_transitive_dependents(loaded, hydra):
    lock, run = loaded
    q = Queries(hydra)
    affected = q.blast_radius(rk(run, "bad"), rel=Edge.DEPENDS_ON, max_len=10)
    assert "pkg:npm:shared" not in affected  # sanity: we compare release keys below
    assert rk(run, "shared") in affected
    assert rk(run, "app") in affected


def test_blast_radius_reaches_the_root_project(loaded, hydra):
    """The root must be a Release too, or a transitive chain has nowhere to land."""
    lock, run = loaded
    q = Queries(hydra)
    affected = q.blast_radius(rk(run, "bad"), rel=Edge.DEPENDS_ON, max_len=10)
    assert release_key("npm", lock.root_name, "1.0.0") in affected


def test_blast_radius_excludes_unrelated_branches(loaded, hydra):
    lock, run = loaded
    q = Queries(hydra)
    affected = q.blast_radius(rk(run, "bad"), rel=Edge.DEPENDS_ON, max_len=10)
    assert rk(run, "other") not in affected
    assert rk(run, "unrelated") not in affected


def test_blast_radius_respects_max_len(loaded, hydra):
    lock, run = loaded
    q = Queries(hydra)
    # bad <- shared <- app <- root is 3 hops; 1 hop must miss the root.
    close = q.blast_radius(rk(run, "bad"), rel=Edge.DEPENDS_ON, max_len=1)
    assert rk(run, "shared") in close
    assert release_key("npm", lock.root_name, "1.0.0") not in close


# -- exposed services: the "is it me" question -------------------------------


def test_exposed_services_finds_transitive_resolution(loaded, hydra):
    """A lockfile pins transitive versions exactly -- this must not require a
    direct dependency to answer "did we resolve the bad version"."""
    from adit.graph.ids import service_key

    lock, run = loaded
    q = Queries(hydra)
    exposed = q.exposed_services(rk(run, "bad"))
    assert any(row["service"] == service_key(lock.root_name) for row in exposed)
    assert exposed[0]["source"] == "test"


def test_exposed_services_is_empty_for_unresolved_release(loaded, hydra):
    q = Queries(hydra)
    assert q.exposed_services(release_key("npm", "never-installed", "9.9.9")) == []


@pytest.mark.parametrize(
    ("start", "end", "expect_hit"),
    [
        (0, 2_000, True),    # window overlaps valid_from=1000
        (0, 500, False),     # window ends before valid_from: genuinely too early
        (2_000, 3_000, True),  # a Resolution has no lockfile-recorded expiry --
        # it is presumed to still hold until a newer lockfile supersedes it, so
        # any window after valid_from correctly still matches. Getting this
        # backwards would make "was it live" silently stop finding services
        # the moment the query window moved past install time.
    ],
)
def test_exposed_services_respects_the_temporal_window(loaded, hydra, start, end, expect_hit):
    lock, run = loaded
    q = Queries(hydra)
    exposed = q.exposed_services(rk(run, "bad"), start, end)
    assert bool(exposed) is expect_hit
