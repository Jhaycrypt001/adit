"""URL validation for the hosted API's git-clone-by-URL flow.

This is the SSRF guard replacing the old path-based /scan -- a client used to
be able to name any file the server process could read; now they name a
github.com repo instead. Each case here is a real class of URL-parser
disagreement or credential-smuggling trick, not a hypothetical one, because
this list is a security boundary and deserves to be tested like one.
"""

from __future__ import annotations

import pytest

from adit.remote import (
    CloneFailed,
    DependencyInstallFailed,
    InvalidRepoUrl,
    cloned_repo,
    install_dependencies,
    validate_github_url,
)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/expressjs/express",
         "https://github.com/expressjs/express.git"),
        ("https://github.com/expressjs/express.git",
         "https://github.com/expressjs/express.git"),
        ("https://github.com/expressjs/express/",
         "https://github.com/expressjs/express.git"),
        ("https://github.com/a1-b2_c3/repo.name-2",
         "https://github.com/a1-b2_c3/repo.name-2.git"),
    ],
)
def test_accepts_and_normalises_real_github_urls(url, expected):
    assert validate_github_url(url) == expected


@pytest.mark.parametrize(
    ("url", "why"),
    [
        ("http://github.com/expressjs/express", "not https"),
        ("ftp://github.com/expressjs/express", "not https"),
        ("file:///etc/passwd", "not https, not github.com"),
        ("git://github.com/expressjs/express", "not https"),
        # subdomain / lookalike-host tricks
        ("https://github.com.evil.com/expressjs/express", "wrong host"),
        ("https://evil-github.com/expressjs/express", "wrong host"),
        ("https://notgithub.com/expressjs/express", "wrong host"),
        ("https://github.com.attacker.io/x/y", "wrong host"),
        # userinfo credential-smuggling: some parsers read the HOST as
        # "github.com" here and IGNORE what looks like a path -- others treat
        # this whole thing as auth against a DIFFERENT host entirely.
        ("https://github.com@evil.com/expressjs/express", "userinfo trick"),
        ("https://user:pass@github.com/expressjs/express", "embedded creds"),
        # SSRF into internal/loopback targets
        ("https://127.0.0.1/expressjs/express", "not github.com"),
        ("https://localhost/expressjs/express", "not github.com"),
        ("https://169.254.169.254/latest/meta-data/", "cloud metadata endpoint"),
        ("https://[::1]/expressjs/express", "not github.com"),
        # non-standard port (could be pointed at an internal service on 443
        # of a different host, or another port entirely on github.com itself)
        ("https://github.com:8443/expressjs/express", "non-standard port"),
        # malformed / incomplete paths
        ("https://github.com/", "no owner or repo"),
        ("https://github.com/justowner", "no repo"),
        ("https://github.com/../../etc/passwd", "path traversal shape"),
        ("not-a-url-at-all", "unparseable"),
        ("", "empty"),
    ],
)
def test_rejects_every_ssrf_and_lookalike_shape(url, why):
    with pytest.raises(InvalidRepoUrl):
        validate_github_url(url)


def test_rejection_never_leaks_toward_a_clone_attempt():
    """A rejected URL must fail during validation, before any subprocess or
    network call is even considered -- confirmed by validate_github_url being
    a pure function with no side effect, exercised directly here rather than
    through cloned_repo (which would need a live network call to prove)."""
    with pytest.raises(InvalidRepoUrl):
        validate_github_url("https://169.254.169.254/")
    # No assertion beyond the raise: reaching this line at all means nothing
    # downstream ran, since validate_github_url has no side effects to undo.


# -- live: real clone, real cleanup ------------------------------------------


@pytest.mark.integration
def test_clones_a_real_small_public_repo():
    """octocat/Hello-World is GitHub's own canonical tiny test repo -- picked
    because it is small and guaranteed stable, not because it is realistic;
    the demo/express clones elsewhere in this project cover realism."""
    with cloned_repo("https://github.com/octocat/Hello-World") as tmpdir:
        assert tmpdir.is_dir()
        assert any(tmpdir.iterdir()), "clone produced an empty directory"
        assert (tmpdir / ".git").exists()
    assert not tmpdir.exists(), "temp directory was not cleaned up after the block"


@pytest.mark.integration
def test_cleans_up_even_when_the_caller_raises():
    captured_path = None
    with pytest.raises(RuntimeError, match="boom"):
        with cloned_repo("https://github.com/octocat/Hello-World") as tmpdir:
            captured_path = tmpdir
            raise RuntimeError("boom")
    assert captured_path is not None
    assert not captured_path.exists(), "temp directory leaked after an exception"


@pytest.mark.integration
def test_a_real_but_nonexistent_repo_raises_clonefailed_and_still_cleans_up():
    """git creates the target directory before it knows the clone will fail --
    this proves that half-created directory doesn't leak either."""
    import tempfile
    from pathlib import Path

    before = set(Path(tempfile.gettempdir()).glob("adit-scan-*"))
    url = "https://github.com/octocat/this-repo-genuinely-does-not-exist-adit-test"
    with pytest.raises(CloneFailed):
        with cloned_repo(url):
            pass  # should never reach here
    after = set(Path(tempfile.gettempdir()).glob("adit-scan-*"))
    assert after <= before, "a failed clone left its temp directory behind"


def test_install_dependencies_refuses_a_repo_with_no_package_json(tmp_path):
    """octocat/Hello-World is a real repo, just not an npm one -- confirmed
    directly that at least one npm version (node:20-slim's bundled npm,
    inside the adit-api container) exits 0 and writes a degenerate
    `package-lock.json` with no `packages` map in this situation rather than
    erroring, which then reached `lockfile.parse_package_lock` as an
    unhandled `ValueError` -- a 500 through the hosted API, not the clean
    4xx this module exists to guarantee. Checked before shelling out to npm
    at all, so behaviour no longer depends on one npm version's opinion."""
    with pytest.raises(DependencyInstallFailed, match="no package.json"):
        install_dependencies(tmp_path)


# -- live: install_dependencies() never runs the untrusted repo's own code --


@pytest.mark.integration
def test_install_dependencies_generates_a_lockfile_when_none_is_committed():
    """express is the real-world case this exists for: it ships its own
    .npmrc setting package-lock=false, so nothing is committed to clone."""
    with cloned_repo("https://github.com/expressjs/express") as root:
        assert not (root / "package-lock.json").exists(), (
            "fixture assumption broke: express started committing a lockfile"
        )
        install_dependencies(root)
        assert (root / "package-lock.json").is_file()
        assert (root / "node_modules").is_dir()
        assert any((root / "node_modules").iterdir())


@pytest.mark.integration
def test_install_dependencies_never_executes_a_postinstall_script():
    """The actual security property, proven rather than assumed: a package
    with a postinstall hook that would leave a detectable side effect if it
    ran must NOT have that side effect after install_dependencies()."""
    import json
    import tempfile
    from pathlib import Path

    root = Path(tempfile.mkdtemp(prefix="adit-test-"))
    try:
        marker = root / "PWNED"
        (root / "package.json").write_text(json.dumps({
            "name": "postinstall-canary",
            "version": "1.0.0",
            "scripts": {
                # If --ignore-scripts is not actually honoured, this file
                # will exist after install_dependencies() returns.
                "postinstall": f'node -e "require(\'fs\').writeFileSync(\'{marker.name}\', \'x\')"',
            },
        }), encoding="utf-8")

        install_dependencies(root)

        assert not marker.exists(), (
            "postinstall script executed -- --ignore-scripts was not honoured"
        )
    finally:
        import shutil

        shutil.rmtree(root, ignore_errors=True)
