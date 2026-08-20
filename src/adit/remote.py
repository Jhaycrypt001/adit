"""Fetch a repository from a URL into an isolated, temporary directory.

Exists specifically for the hosted API. `POST /scan` used to take a raw
filesystem `path` -- fine for the CLI (same trust boundary as running any
command on your own machine) but an arbitrary-file-read vulnerability the
moment `/scan` is reachable from the public internet, since that path is
resolved on the *server*, not the client. This is the replacement: a client
gives a URL, the server clones it into a directory nothing else can guess,
and always removes it afterward.

Validation is defense in depth, not one check: only `https://github.com/`
URLs are accepted; the URL is parsed and **rebuilt** from validated
components rather than passed through as given, so a discrepancy between
`urlparse` and whatever `git` itself parses can't be exploited (a caller
passing validation while smuggling something the two parsers disagree about
is a real, documented SSRF bypass class); and cloning runs via
`subprocess.run` with an argument list, never a shell string, so nothing in
the URL can smuggle a second command.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from functools import cache
from pathlib import Path
from urllib.parse import urlparse

log = logging.getLogger(__name__)

CLONE_TIMEOUT_SECONDS = 60
NPM_TIMEOUT_SECONDS = 180

_OWNER_REPO = re.compile(
    r"^/(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)"
    r"/(?P<repo>[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)(?:\.git)?/?$"
)


class InvalidRepoUrl(ValueError):
    """The URL is not an acceptable `https://github.com/<owner>/<repo>`."""


class CloneFailed(RuntimeError):
    """`git clone` itself failed (bad repo, private, network, timeout)."""


class DependencyInstallFailed(RuntimeError):
    """`npm ci`/`npm install` failed (bad manifest, network, timeout)."""


@cache
def _resolve(executable: str) -> str:
    """Find `executable` the way the OS actually resolves it, extension and
    all -- `subprocess.run([executable, ...])` without `shell=True` calls
    `CreateProcess` directly on Windows, which does NOT apply `PATHEXT`
    resolution the way a shell does. `npm` on Windows is a `.cmd` wrapper
    around the real entry point, so a bare `"npm"` here failed outright with
    `FileNotFoundError: [WinError 2]` -- confirmed by two tests that could
    not even reach their actual assertions. `shutil.which` performs the same
    PATH+PATHEXT search a shell would without needing `shell=True`, which
    would reopen a shell-metacharacter injection surface for no reason none
    of these arguments need.
    """
    found = shutil.which(executable)
    if found is None:
        raise RuntimeError(f"{executable!r} not found on PATH")
    return found


def validate_github_url(url: str) -> str:
    """Accept only a clean `https://github.com/<owner>/<repo>` URL.

    Returns a **rebuilt** canonical URL, deliberately not the caller's
    original string -- see the module docstring for why.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise InvalidRepoUrl("only https:// URLs are accepted")
    if parsed.username or parsed.password:
        raise InvalidRepoUrl("URLs with embedded credentials are rejected")
    if parsed.hostname != "github.com":
        raise InvalidRepoUrl("only github.com repository URLs are accepted")
    if parsed.port not in (None, 443):
        raise InvalidRepoUrl("non-standard port rejected")
    match = _OWNER_REPO.match(parsed.path)
    if not match:
        raise InvalidRepoUrl("expected https://github.com/<owner>/<repo>")
    # `.` is a valid character inside a real repo name (e.g. "repo.name-2"),
    # so the regex's own optional `(?:\.git)?` suffix is ambiguous with a
    # greedy repo-name match -- "express.git" matches with ".git" consumed
    # INTO the repo group, not trimmed by the suffix, which appended it a
    # second time below. Stripping explicitly in code sidesteps the
    # ambiguity instead of fighting regex greediness for a case that is
    # inherently ambiguous from the pattern alone.
    repo = match["repo"].removesuffix(".git")
    return f"https://github.com/{match['owner']}/{repo}.git"


def _force_remove_readonly(func, path, exc_info) -> None:  # noqa: ANN001
    """`shutil.rmtree`'s error hook: git marks packed objects read-only, and
    on Windows that makes plain `rmtree` fail outright -- confirmed directly:
    `ignore_errors=True` was silently swallowing exactly this failure, so a
    "cleaned up" scan was in fact leaking a full repo clone onto disk every
    time, caught only because a test asserted the directory was gone rather
    than trusting the context manager not to raise. Clear the read-only bit
    and retry once; if that still fails, let it raise for real -- silence is
    what caused this to go unnoticed the first time.

    `onerror`, not the newer `onexc` (Python 3.12+): pyproject.toml targets
    3.11+, and this callback's three-argument `(func, path, exc_info)` shape
    is `onerror`'s signature specifically -- `onexc` passes the exception
    instance as the third argument instead, a different shape entirely.
    `onerror` is deprecated as of 3.12 but not removed, so this keeps working
    across the whole supported range without a version-gated code path.
    """
    os.chmod(path, stat.S_IWRITE)
    func(path)


@contextmanager
def cloned_repo(url: str) -> Iterator[Path]:
    """Clone `url` into an isolated temp directory. Always cleaned up.

    A shallow, single-branch, tagless clone -- this is a security scan, not a
    checkout someone will develop against, so history and refs beyond the
    default branch are unneeded weight.
    """
    clean_url = validate_github_url(url)
    tmpdir = Path(tempfile.mkdtemp(prefix="adit-scan-"))
    try:
        result = subprocess.run(  # noqa: S603 -- argument list, not a shell string
            [_resolve("git"), "clone", "--depth", "1", "--single-branch", "--no-tags",
             clean_url, str(tmpdir)],
            capture_output=True, text=True, timeout=CLONE_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            raise CloneFailed(result.stderr.strip()[:500] or "git clone failed")
        yield tmpdir
    finally:
        try:
            shutil.rmtree(tmpdir, onerror=_force_remove_readonly)
        except Exception:  # noqa: BLE001
            # A hosted service must never crash a request over cleanup, but
            # silently losing the failure is exactly what let the read-only
            # bug above go unnoticed -- log it loudly instead of swallowing.
            log.error("failed to remove temp clone dir %s", tmpdir, exc_info=True)


#: How many candidate subdirectories to name in a "wrong root" error before
#: truncating. Enough to be actionable, short enough to stay one line.
_SUGGEST_LIMIT = 5

#: Directories that never contain the project being scanned, and would
#: otherwise dominate the suggestions on any repo that has been installed.
_SKIP_DIRS = {"node_modules", ".git", "dist", "build", "vendor", ".venv", "__pycache__"}


def _find_npm_projects(root: Path, *, max_depth: int = 2) -> list[str]:
    """Relative paths of directories under `root` that hold a package.json.

    Shallow on purpose: a package.json six levels down is a fixture or a
    vendored copy far more often than it is the thing the caller meant.
    """
    out: list[str] = []
    for path in sorted(root.rglob("package.json")):
        try:
            rel = path.parent.relative_to(root)
        except ValueError:  # pragma: no cover -- rglob cannot leave root
            continue
        parts = rel.parts
        if not parts or len(parts) > max_depth:
            continue
        if any(p in _SKIP_DIRS for p in parts):
            continue
        out.append("/".join(parts))
    return out


def install_dependencies(root: Path) -> None:
    """Populate `node_modules` (and a lockfile, if the repo doesn't commit
    one) for a freshly cloned repo -- WITHOUT running any of its install or
    postinstall scripts.

    `--ignore-scripts` is not a performance shortcut, it is the entire point.
    This is the exact install-time-payload threat Adit itself exists to
    detect (see the real 2018 event-stream/flatmap-stream attack this
    project demonstrates elsewhere) -- running an ARBITRARY public repo's
    install scripts on infrastructure that accepts arbitrary public repo
    URLs would hand remote code execution to whoever submits a malicious
    one. Adit's whole method is static analysis of whether a payload WOULD
    run; it never needs the payload to actually run, so there is no
    correctness cost to refusing to run it. A CLI flag beats trying to
    sanitise the untrusted repo's own `.npmrc` some other way: npm's config
    precedence puts a command-line flag above every `.npmrc` it could
    contain, project-level included.

    Most real repositories -- confirmed directly on express, which ships its
    own `.npmrc` setting `package-lock=false` -- do not commit a lockfile at
    all, so `npm ci` (which requires one) is not always usable; falls back
    to `npm install --package-lock=true` to generate one when absent.

    Checked before shelling out at all: a repo with no `package.json`
    (e.g. octocat/Hello-World -- a real repo, just not an npm one) is not
    a dependency-install failure npm reliably reports as one. Confirmed
    directly running this container's bundled npm (node:20-slim, newer
    than the version this was first tested against on the host) against
    such a repo: it exited 0 and wrote a `package-lock.json` with a
    `lockfileVersion` but no `packages` map at all, which then blew up
    `lockfile.parse_package_lock` as an *unhandled* `ValueError` deep
    inside `scan()` -- a 500, not the clean 4xx this whole module exists
    to guarantee. Different npm versions disagree about whether that's an
    error; not depending on that behaviour is more robust than chasing it.
    """
    if not (root / "package.json").is_file():
        # A repository whose npm project lives one level down -- a monorepo, or
        # a frontend beside a backend in another language -- is the common case
        # here, not a malformed repo. Saying only "not an npm project" sends the
        # caller away when the answer is one directory below, so the ones we can
        # see get named.
        found = _find_npm_projects(root)
        if found:
            listed = ", ".join(found[:_SUGGEST_LIMIT])
            more = f" (+{len(found) - _SUGGEST_LIMIT} more)" if len(found) > _SUGGEST_LIMIT else ""
            raise DependencyInstallFailed(
                f"no package.json at the repository root, but found one in: "
                f"{listed}{more}. Re-run with that path as `subdir`."
            )
        raise DependencyInstallFailed("no package.json found -- not an npm project")
    has_lockfile = (root / "package-lock.json").is_file()
    npm = _resolve("npm")
    cmd = (
        [npm, "ci", "--ignore-scripts"] if has_lockfile
        else [npm, "install", "--ignore-scripts", "--package-lock=true"]
    )
    try:
        result = subprocess.run(  # noqa: S603 -- argument list, not a shell string
            cmd, cwd=root, capture_output=True, text=True, timeout=NPM_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise DependencyInstallFailed(
            f"dependency install exceeded {NPM_TIMEOUT_SECONDS}s"
        ) from exc
    if result.returncode != 0:
        raise DependencyInstallFailed(result.stderr.strip()[:500] or "npm install failed")
