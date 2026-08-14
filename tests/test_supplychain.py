"""Lockfile resolution, advisory classification, and symbol resolution.

All offline. The network-dependent paths are exercised by scripts/probe_*.py
against live OSV; what is pinned here is the logic that decides *which* answer
Adit gives, because those are the decisions that would silently produce
confident nonsense if wrong.
"""

from __future__ import annotations

import json

import pytest

from adit.graph.schema import AdvisoryClass
from adit.ingest.lockfile import parse_package_lock
from adit.ingest.osv import Advisory, classify
from adit.ingest.symbols import candidates_from_text, fallback, from_prose

# -- lockfile ---------------------------------------------------------------

LOCK = {
    "name": "shop",
    "version": "1.0.0",
    "lockfileVersion": 3,
    "packages": {
        "": {"name": "shop", "version": "1.0.0", "dependencies": {"a": "^1", "lodash": "^4"}},
        "node_modules/a": {"version": "1.0.0", "dependencies": {"lodash": "^3"}},
        # Nested copy: `a` must resolve to THIS lodash, not the hoisted one.
        "node_modules/a/node_modules/lodash": {"version": "3.10.1"},
        "node_modules/lodash": {"version": "4.17.20"},
        "node_modules/esbuild": {"version": "0.20.0", "hasInstallScript": True},
    },
}


@pytest.fixture
def lock(tmp_path):
    path = tmp_path / "package-lock.json"
    path.write_text(json.dumps(LOCK), encoding="utf-8")
    return parse_package_lock(path)


def test_reads_root_identity(lock):
    assert (lock.root_name, lock.root_version) == ("shop", "1.0.0")
    assert lock.lockfile_version == 3


def test_installs_every_package_with_exact_versions(lock):
    specs = {p.spec for p in lock.packages.values()}
    assert specs == {"a@1.0.0", "lodash@3.10.1", "lodash@4.17.20", "esbuild@0.20.0"}


def test_nested_node_modules_shadows_the_hoisted_copy(lock):
    """`a` depends on lodash 3, not the hoisted lodash 4. Getting this wrong
    attaches edges to the wrong version and makes blast radius quietly wrong."""
    targets = {dst for src, dst in lock.edges if src == "node_modules/a"}
    assert "node_modules/a/node_modules/lodash" in targets
    assert "node_modules/lodash" not in targets


def test_root_edges_use_the_hoisted_copy(lock):
    targets = {dst for src, dst in lock.edges if src == ""}
    assert "node_modules/lodash" in targets


def test_install_scripts_are_flagged(lock):
    assert {p.name for p in lock.install_scripted} == {"esbuild"}


def test_bom_prefixed_lockfile_still_parses(tmp_path):
    """Windows-authored JSON carries a BOM; json.loads rejects it outright."""
    path = tmp_path / "package-lock.json"
    path.write_text(json.dumps(LOCK), encoding="utf-8-sig")
    assert parse_package_lock(path).root_name == "shop"


def test_v1_lockfile_is_refused_not_half_parsed(tmp_path):
    path = tmp_path / "package-lock.json"
    path.write_text(json.dumps({"lockfileVersion": 1, "dependencies": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="lockfileVersion"):
        parse_package_lock(path)


# -- advisory classification ------------------------------------------------


def adv(id_="GHSA-x", summary="", details="") -> Advisory:
    return Advisory(id=id_, summary=summary, details=details, severity="HIGH")


@pytest.mark.parametrize(
    ("advisory", "has_script", "expected"),
    [
        # OSV's malicious-package database. The package IS the attack.
        (adv("MAL-2026-1234", "malicious code in flatmap-stream"), False,
         AdvisoryClass.INSTALL_TIME),
        (adv(summary="Malicious code executed via preinstall script"), False,
         AdvisoryClass.INSTALL_TIME),
        (adv(details="runs a postinstall hook that exfiltrates credentials"), False,
         AdvisoryClass.INSTALL_TIME),
        # Hostile wording alone is not enough -- advisories discuss supply-chain
        # risk in passing all the time.
        (adv(summary="supply-chain risk discussed in this ReDoS report"), False,
         AdvisoryClass.RUNTIME),
        # ...but combined with an actual install script, it is.
        (adv(summary="compromised release exfiltrates tokens"), True,
         AdvisoryClass.INSTALL_TIME),
        # Ordinary library CVE.
        (adv(summary="Prototype Pollution in `_.unset`"), False, AdvisoryClass.RUNTIME),
        (adv(), False, AdvisoryClass.UNKNOWN),
    ],
)
def test_classification_picks_the_right_question(advisory, has_script, expected):
    assert classify(advisory, has_install_script=has_script) is expected


# -- symbol resolution ------------------------------------------------------


def test_extracts_underscore_qualified_names():
    found = candidates_from_text("Prototype Pollution via `_.unset` and `_.omit`")
    assert "unset" in found
    assert "omit" in found


def test_extracts_code_spans_and_call_forms():
    found = candidates_from_text("The `template` helper and merge() are affected")
    assert "template" in found
    assert "merge" in found


def test_does_not_scan_bare_words():
    """Bare-word matching would hit English against exports like `has` or `get`."""
    found = candidates_from_text("this vulnerability has a template for escape behaviour")
    assert "has" not in found
    assert "escape" not in found


def test_prose_names_only_survive_if_really_exported():
    """The guard that stops phantom targets producing confident, wrong paths."""
    advisory = adv(summary="Pollution in `_.unset` and `_.notARealExport`")
    res = from_prose(advisory, exports={"unset", "omit"})
    assert res is not None
    assert res.symbols == ["unset"]
    assert "notARealExport" in res.rejected
    assert res.tier == 1
    assert res.confidence == 0.9


def test_prose_with_no_real_exports_declines_rather_than_guessing():
    advisory = adv(summary="Pollution in `_.somethingElse`")
    assert from_prose(advisory, exports={"unset"}) is None


def test_fallback_is_labelled_as_a_fallback():
    res = fallback({"a", "b"})
    assert res.tier == 3
    assert res.confidence == 0.4
    assert not res.resolved
    assert "public API" in res.describe()


def test_resolved_flag_distinguishes_real_answers():
    assert from_prose(adv(summary="`_.unset` bug"), {"unset"}).resolved
    assert not fallback({"unset"}).resolved
