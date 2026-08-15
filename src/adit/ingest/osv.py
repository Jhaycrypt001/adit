"""Advisory lookup via OSV, and the classification that decides the analysis.

OSV is free, needs no authentication and enforces no rate limits, which is what
keeps Adit's critical path free of API keys and LLM spend.

Two things here matter more than the plumbing:

**Classification.** An advisory is either install-time or runtime, and they need
opposite analysis. A preinstall hook (the keyv compromise, the TanStack worm)
executes at `npm install` whether or not anything imports the package, so
reachability is *meaningless* and blast radius is the whole answer. An ordinary
library CVE is the reverse: everyone depends on lodash, so blast radius is noise
and reachability is everything. Most tools conflate the two and rank badly as a
result.

**Batching.** `/v1/querybatch` returns only vulnerability IDs; details need a
second call per unique ID. Deduplicating before that second pass matters,
because one advisory routinely affects many installed packages.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..graph.schema import AdvisoryClass

log = logging.getLogger(__name__)

OSV_API = "https://api.osv.dev"
BATCH_LIMIT = 1000  # OSV accepts far more, but keeps responses inside 32MiB

#: Wording that indicates code runs at install time rather than on call.
_INSTALL_HOOK = re.compile(
    r"\b(pre|post)?install\s*(script|hook)?\b|\bnpm\s+install\b|"
    r"\blifecycle\s+script\b|\bpreinstall\b|\bpostinstall\b",
    re.IGNORECASE,
)

#: Wording that indicates the package itself is hostile, not merely defective.
_MALICIOUS = re.compile(
    r"\bmalicious\b|\bmalware\b|\bbackdoor\b|\btrojan\b|\bcompromised\b|"
    r"\bexfiltrat\w*\b|\bcredential\s+(harvest|steal)\w*\b|\bsupply[- ]chain\b|"
    r"\btyposquat\w*\b|\bworm\b",
    re.IGNORECASE,
)


@dataclass(slots=True)
class Advisory:
    """One OSV record, reduced to what Adit reasons about."""

    id: str
    summary: str
    details: str
    severity: str
    aliases: list[str] = field(default_factory=list)
    #: package name -> (introduced, fixed) version strings
    affected: dict[str, tuple[str, str]] = field(default_factory=dict)
    references: list[tuple[str, str]] = field(default_factory=list)  # (type, url)
    published: str = ""
    modified: str = ""
    klass: AdvisoryClass = AdvisoryClass.UNKNOWN

    @property
    def text(self) -> str:
        return f"{self.summary}\n{self.details}"

    def fix_references(self) -> list[str]:
        """URLs likely to contain the patch, best first.

        Used by the tier-2 symbol resolver: the functions a fix touches are the
        functions that were vulnerable.
        """
        ranked = [u for t, u in self.references if t == "FIX"]
        ranked += [
            u for t, u in self.references
            if t in ("WEB", "ADVISORY") and re.search(r"/(commit|pull)/", u)
        ]
        return ranked


def classify(advisory: Advisory, *, has_install_script: bool = False) -> AdvisoryClass:
    """Decide whether reachability or blast radius is the right question.

    Ordered by how much each signal is worth:

    1. `MAL-` identifiers come from OSV's malicious-package database. The
       package *is* the attack; nothing about call graphs applies.
    2. Explicit mention of an install or lifecycle hook.
    3. Hostile-intent wording combined with the lockfile recording that this
       package actually declares an install script. Neither is conclusive
       alone -- plenty of advisories discuss supply-chain risk in passing, and
       plenty of benign packages have install scripts -- but together they are.
    """
    if advisory.id.upper().startswith("MAL-"):
        return AdvisoryClass.INSTALL_TIME
    if _INSTALL_HOOK.search(advisory.text):
        return AdvisoryClass.INSTALL_TIME
    if has_install_script and _MALICIOUS.search(advisory.text):
        return AdvisoryClass.INSTALL_TIME
    if advisory.summary or advisory.details:
        return AdvisoryClass.RUNTIME
    return AdvisoryClass.UNKNOWN


def _parse(raw: dict[str, Any]) -> Advisory:
    affected: dict[str, tuple[str, str]] = {}
    for entry in raw.get("affected") or []:
        pkg = (entry.get("package") or {}).get("name")
        if not pkg:
            continue
        introduced = fixed = ""
        for rng in entry.get("ranges") or []:
            for event in rng.get("events") or []:
                introduced = event.get("introduced", introduced) or introduced
                fixed = event.get("fixed", fixed) or fixed
        affected[pkg] = (introduced, fixed)

    severity = ""
    for sev in raw.get("severity") or []:
        severity = sev.get("score", "") or severity
    if not severity:
        severity = str((raw.get("database_specific") or {}).get("severity", "") or "")

    return Advisory(
        id=str(raw.get("id", "")),
        summary=str(raw.get("summary", "") or ""),
        details=str(raw.get("details", "") or ""),
        severity=severity,
        aliases=[str(a) for a in (raw.get("aliases") or [])],
        affected=affected,
        references=[
            (str(r.get("type", "")), str(r.get("url", "")))
            for r in (raw.get("references") or [])
        ],
        published=str(raw.get("published", "") or ""),
        modified=str(raw.get("modified", "") or ""),
    )


class OsvClient:
    """Minimal OSV client: batch query, then fetch unique advisories."""

    def __init__(self, *, timeout: float = 30.0, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(
            base_url=OSV_API,
            timeout=timeout,
            headers={"User-Agent": "adit/0.1 (+https://github.com/adit)"},
        )
        self._owned = client is None

    def close(self) -> None:
        if self._owned:
            self._client.close()

    def __enter__(self) -> OsvClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _post(self, path: str, payload: dict, *, retries: int = 3) -> httpx.Response:
        """POST with retry. OSV is free and unauthenticated, which also means
        no SLA -- a dropped connection here should not kill a live scan."""
        delay = 0.5
        for attempt in range(1, retries + 1):
            try:
                resp = self._client.post(path, json=payload)
                resp.raise_for_status()
                return resp
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                if attempt == retries:
                    raise
                log.warning("OSV %s attempt %d/%d failed: %s", path, attempt, retries, exc)
                time.sleep(delay)
                delay *= 2
        raise AssertionError("unreachable")

    def query_batch(self, specs: list[tuple[str, str]]) -> dict[tuple[str, str], list[str]]:
        """Map (name, version) -> advisory ids. One request per BATCH_LIMIT."""
        out: dict[tuple[str, str], list[str]] = {}
        for start in range(0, len(specs), BATCH_LIMIT):
            chunk = specs[start : start + BATCH_LIMIT]
            payload = {
                "queries": [
                    {"package": {"name": n, "ecosystem": "npm"}, "version": v}
                    for n, v in chunk
                ]
            }
            resp = self._post("/v1/querybatch", payload)
            results = resp.json().get("results") or []
            for spec, result in zip(chunk, results, strict=False):
                ids = [v["id"] for v in (result.get("vulns") or []) if "id" in v]
                if ids:
                    out[spec] = ids
        return out

    def fetch(self, advisory_id: str, *, retries: int = 3) -> Advisory | None:
        delay = 0.5
        for attempt in range(1, retries + 1):
            try:
                resp = self._client.get(f"/v1/vulns/{advisory_id}")
                resp.raise_for_status()
                return _parse(resp.json())
            except httpx.HTTPError as exc:
                if attempt == retries:
                    log.warning("could not fetch %s: %s", advisory_id, exc)
                    return None
                time.sleep(delay)
                delay *= 2
        return None

    def fetch_many(self, ids: list[str]) -> dict[str, Advisory]:
        """Fetch unique advisories. One advisory commonly affects many packages."""
        out: dict[str, Advisory] = {}
        for advisory_id in dict.fromkeys(ids):  # dedupe, preserve order
            advisory = self.fetch(advisory_id)
            if advisory is not None:
                out[advisory_id] = advisory
        return out
