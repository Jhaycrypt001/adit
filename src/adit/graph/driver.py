"""HydraDB connection and statement execution.

Adit talks to HydraDB purely as a network client over Bolt. The engine is used
unmodified and never vendored -- it is AGPL-3.0 and Adit ships Apache-2.0, so
that boundary is deliberate. See ARCHITECTURE.md section 8.

Two engine facts shape this module:

  * Explicit transactions are rejected ("use auto-commit RUN queries"), so there
    is no unit of atomicity larger than one statement. Every writer must be
    idempotent, and a failed run must be safe to repeat.
  * Admission control rejects any batch over 1024 rows, so all batched work is
    chunked here rather than at each call site.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Iterable, Iterator, Sequence
from typing import Any

from neo4j import Driver, GraphDatabase
from neo4j.exceptions import Neo4jError, ServiceUnavailable, TransientError

log = logging.getLogger(__name__)

#: Admission control rejects larger batches outright:
#: "client_query_batch_items rejected by admission control: actual 2000 exceeds limit 1024"
MAX_BATCH = 1024

DEFAULT_URI = "bolt://127.0.0.1:7687"
DEFAULT_TOKEN = "local-development-token-32-bytes"  # noqa: S105 - local dev default


def chunked(rows: Sequence[dict[str, Any]], size: int = MAX_BATCH) -> Iterator[list[dict]]:
    """Split rows into engine-acceptable batches."""
    if size > MAX_BATCH:
        raise ValueError(f"batch size {size} exceeds engine limit {MAX_BATCH}")
    for i in range(0, len(rows), size):
        yield list(rows[i : i + size])


class Hydra:
    """A thin, retrying wrapper over the Bolt driver."""

    def __init__(
        self,
        uri: str | None = None,
        token: str | None = None,
        *,
        max_retries: int = 3,
    ) -> None:
        self.uri = uri or os.environ.get("ADIT_BOLT_URI", DEFAULT_URI)
        token = token or os.environ.get("ADIT_BOLT_TOKEN", DEFAULT_TOKEN)
        self.max_retries = max_retries
        self._driver: Driver = GraphDatabase.driver(self.uri, auth=("neo4j", token))
        # A single long-lived session, created lazily.
        #
        # Opening one per statement costs a Bolt handshake each time, which
        # measured at roughly a second per ten statements -- enough that writing
        # seven symbols took 7.5s and looked like a throughput problem rather
        # than a connection-churn one. There are no explicit transactions in
        # this engine, so one session is all that is needed.
        self._session = None

    # -- lifecycle ---------------------------------------------------------
    def verify(self) -> None:
        self._driver.verify_connectivity()

    def _get_session(self):
        if self._session is None:
            self._session = self._driver.session()
        return self._session

    def _drop_session(self) -> None:
        """Discard a session after an error so the next call reconnects clean."""
        if self._session is not None:
            try:
                self._session.close()
            except Exception:  # noqa: BLE001 - already unwinding
                pass
            self._session = None

    def close(self) -> None:
        self._drop_session()
        self._driver.close()

    def __enter__(self) -> Hydra:
        self.verify()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- execution ---------------------------------------------------------
    def run(self, cypher: str, **params: Any) -> list[dict[str, Any]]:
        """Execute one statement, retrying only genuinely transient failures.

        Syntax errors are raised immediately: with an engine this particular
        about accepted forms, retrying a rejected statement just hides the shape
        problem we need to see.
        """
        delay = 0.25
        for attempt in range(1, self.max_retries + 1):
            try:
                return [r.data() for r in self._get_session().run(cypher, **params)]
            except (TransientError, ServiceUnavailable) as exc:
                self._drop_session()
                if attempt == self.max_retries:
                    raise
                log.warning("transient (%s/%s): %s", attempt, self.max_retries, exc)
                time.sleep(delay)
                delay *= 2
            except Neo4jError:
                raise
        return []  # unreachable

    def run_paths(self, cypher: str, **params: Any) -> list[Any]:
        """Execute a statement whose rows carry a hydrated `path` value.

        `algo.MSpaths` is the only construct that returns a traversable Path
        object, so it needs a result handler that does not flatten to dicts.
        """
        return [r["path"] for r in self._get_session().run(cypher, **params)]

    def run_batched(self, cypher: str, rows: Sequence[dict[str, Any]]) -> int:
        """Run an UNWIND statement over `rows`, chunked to the engine limit.

        Returns the number of rows submitted. The engine cannot return a count
        from a write -- write clauses are terminal -- so this is rows *sent*,
        not rows verified. Callers that need certainty must read back.
        """
        sent = 0
        for batch in chunked(rows):
            self.run(cypher, rows=batch)
            sent += len(batch)
        return sent

    def count(self, label: str) -> int:
        """Count nodes carrying a label. `count(*)` is the only supported form."""
        rows = self.run(f"MATCH (n:{label}) RETURN count(*) AS c")
        return rows[0]["c"] if rows else 0


def flatten(paths: Iterable[Any]) -> list[list[dict[str, Any]]]:
    """Turn hydrated Paths into plain node-property dicts for rendering."""
    out: list[list[dict[str, Any]]] = []
    for path in paths:
        out.append([dict(node) for node in path.nodes])
    return out
