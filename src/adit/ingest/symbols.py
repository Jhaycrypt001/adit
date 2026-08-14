"""Work out *which function* an advisory is actually about.

npm advisories carry no affected-function data. Go and Rust populate
`affected[].ecosystem_specific`; npm leaves it empty. Without a function,
"reachability" collapses into "do I import this package at all", which is what
existing tools already do badly -- so this module is the difference between a
real reachability tool and a re-skinned dependency scanner.

Three tiers, decreasing confidence, and the tier travels with the answer all the
way to the CLI so a weak result is never dressed up as a strong one:

  T1 (0.9)  the advisory prose names it -- "Prototype Pollution in `_.unset`"
  T2 (0.7)  the patch touched it -- functions changed by the fixing commit
  T3 (0.4)  unknown; fall back to the package's public API, and say so

**Every tier is intersected with symbols that actually exist in the package we
parsed.** That single rule is what makes T1 safe: prose naming something which
is not a real export is discarded rather than becoming a phantom target that
produces confident, wrong reachability.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import httpx

from .osv import Advisory

log = logging.getLogger(__name__)

# -- tier 1: prose ----------------------------------------------------------
# Ordered by precision. Only high-precision forms are used: a bare-word scan
# would match English text against exports like `has`, `get`, `escape` or
# `template` and fabricate targets.

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # `_.unset` / `_.template` -- the lodash convention, and unambiguous.
    ("underscore-qualified", re.compile(r"[_$]\.([A-Za-z_$][\w$]*)")),
    # `merge` inside a code span.
    ("code span", re.compile(r"`\s*(?:[_$]\.)?([A-Za-z_$][\w$]*)\s*(?:\(\))?\s*`")),
    # merge() written inline.
    ("call form", re.compile(r"\b([A-Za-z_$][\w$]*)\(\)")),
    # "the merge function" / "function merge"
    ("named function", re.compile(
        r"\bfunction\s+([A-Za-z_$][\w$]*)|\b([A-Za-z_$][\w$]*)\s+function\b"
    )),
)

# -- tier 2: patches --------------------------------------------------------

_HUNK_CONTEXT = re.compile(r"^@@[^@]*@@\s*(?:function\s+)?([A-Za-z_$][\w$]*)", re.MULTILINE)
_CHANGED_DECL = re.compile(
    r"^[+-]\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)"
    r"|^[+-]\s*(?:var|let|const)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:function|\()"
    r"|^[+-]\s*([A-Za-z_$][\w$]*)\s*[:=]\s*function",
    re.MULTILINE,
)

_GITHUB_COMMIT = re.compile(r"https://github\.com/([^/]+)/([^/]+)/commit/([0-9a-f]{7,40})")
_GITHUB_PR = re.compile(r"https://github\.com/([^/]+)/([^/]+)/pull/(\d+)")


@dataclass(slots=True)
class SymbolResolution:
    """Which symbols an advisory implicates, and how sure we are."""

    symbols: list[str]
    tier: int
    confidence: float
    method: str
    #: Names the prose or patch offered that are not real exports. Kept for
    #: diagnostics -- a long list here usually means the package was parsed
    #: incompletely, not that the advisory was wrong.
    rejected: list[str] = field(default_factory=list)

    @property
    def resolved(self) -> bool:
        return self.tier < 3

    def describe(self) -> str:
        if self.tier == 3:
            return "package public API (specific symbol unresolved)"
        return f"{', '.join(self.symbols[:4])}  [{self.method}, confidence {self.confidence}]"


def candidates_from_text(text: str) -> dict[str, str]:
    """Extract candidate identifiers, keeping the most precise pattern per name."""
    found: dict[str, str] = {}
    for label, pattern in _PATTERNS:
        for match in pattern.finditer(text):
            for group in match.groups():
                if group and group not in found and len(group) > 1:
                    found[group] = label
    return found


def from_prose(advisory: Advisory, exports: set[str]) -> SymbolResolution | None:
    """Tier 1. Only names that are genuinely exported survive."""
    candidates = candidates_from_text(advisory.text)
    if not candidates:
        return None
    accepted = [n for n in candidates if n in exports]
    rejected = [n for n in candidates if n not in exports]
    if not accepted:
        return None
    methods = sorted({candidates[n] for n in accepted})
    return SymbolResolution(
        symbols=accepted,
        tier=1,
        confidence=0.9,
        method=f"advisory text ({', '.join(methods)})",
        rejected=rejected,
    )


def _patch_urls(advisory: Advisory) -> list[str]:
    """Turn references into fetchable raw-patch URLs."""
    urls: list[str] = []
    for ref in advisory.fix_references():
        commit = _GITHUB_COMMIT.search(ref)
        if commit:
            owner, repo, sha = commit.groups()
            urls.append(f"https://github.com/{owner}/{repo}/commit/{sha}.patch")
            continue
        pr = _GITHUB_PR.search(ref)
        if pr:
            owner, repo, number = pr.groups()
            urls.append(f"https://github.com/{owner}/{repo}/pull/{number}.diff")
    return urls


def from_patch(
    advisory: Advisory,
    exports: set[str],
    *,
    client: httpx.Client | None = None,
    max_patches: int = 3,
    max_bytes: int = 2_000_000,
) -> SymbolResolution | None:
    """Tier 2. The functions a fix touched are the functions that were vulnerable."""
    urls = _patch_urls(advisory)
    if not urls:
        return None

    owned = client is None
    http = client or httpx.Client(
        timeout=20.0, follow_redirects=True,
        headers={"User-Agent": "adit/0.1 (+https://github.com/adit)"},
    )
    names: dict[str, str] = {}
    try:
        for url in urls[:max_patches]:
            try:
                resp = http.get(url)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                log.debug("patch fetch failed %s: %s", url, exc)
                continue
            body = resp.text[:max_bytes]
            for match in _CHANGED_DECL.finditer(body):
                for group in match.groups():
                    if group:
                        names.setdefault(group, "changed declaration")
            for match in _HUNK_CONTEXT.finditer(body):
                if match.group(1):
                    names.setdefault(match.group(1), "hunk context")
    finally:
        if owned:
            http.close()

    accepted = [n for n in names if n in exports]
    if not accepted:
        return None
    return SymbolResolution(
        symbols=accepted,
        tier=2,
        confidence=0.7,
        method=f"fix patch ({', '.join(sorted({names[n] for n in accepted}))})",
        rejected=[n for n in names if n not in exports],
    )


def fallback(exports: set[str]) -> SymbolResolution:
    """Tier 3. Honest ignorance: the whole public surface, clearly labelled."""
    return SymbolResolution(
        symbols=sorted(exports),
        tier=3,
        confidence=0.4,
        method="package public API",
    )


def resolve(
    advisory: Advisory,
    exports: set[str],
    *,
    client: httpx.Client | None = None,
    allow_network: bool = True,
) -> SymbolResolution:
    """Best available answer for which symbols this advisory implicates."""
    hit = from_prose(advisory, exports)
    if hit is not None:
        return hit
    if allow_network:
        hit = from_patch(advisory, exports, client=client)
        if hit is not None:
            return hit
    return fallback(exports)
