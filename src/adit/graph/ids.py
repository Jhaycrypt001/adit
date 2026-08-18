"""Node identity.

HydraDB requires a property literally named `id` to be an integer, but
`algo.MSpaths` matches on a *string* property. Neither is optional, so every
Adit node carries both:

    id   int    blake2b(key) truncated to 63 bits -- engine identity
    key  str    canonical human-readable identity -- MSpaths match target

The key is the source of truth. The id is derived, so any two ingest stages that
independently mention the same entity converge on the same node without
coordination -- which matters because HydraDB has no explicit transactions and
ingest must be safely re-runnable.
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from hashlib import blake2b

# Postgres-style: stay inside signed 64-bit so no driver or engine narrows it.
_MASK = (1 << 63) - 1

# Request-scoped isolation for a hosted, multi-tenant API.
#
# HydraDB rejects any graph-database name it wasn't started with --
# `session(database="scan-xyz")` fails with "unknown graph database"
# (confirmed live; per-request engine-level databases are not an option this
# engine offers). So isolation happens one level up: every scan gets a random
# namespace folded into its ids before hashing, all sharing the one "default"
# graph HydraDB actually has. Two scans of the identical repo get disjoint id
# spaces and cannot collide or see each other's data -- not because the data
# is deleted (it isn't; there is no expiry mechanism), but because nothing
# outside that scan's own response ever learns its namespace. "Ephemeral"
# here means "not globally discoverable," stated precisely rather than
# implying deletion that doesn't happen.
#
# A ContextVar rather than a thread-local or a Writer/Queries constructor
# argument: FastAPI serves concurrent requests on one event loop, and
# ContextVar is the primitive that stays correctly isolated per request
# under that concurrency model without threading a namespace parameter
# through every function signature in graph/ and ingest/.
_namespace: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "adit_scan_namespace", default=None
)


@contextmanager
def scan_scope(namespace: str) -> Iterator[None]:
    """Fold `namespace` into every node_id() derived inside this block.

    The CLI and every existing test never call this, so `node_id()` keeps
    hashing bare keys exactly as before for them -- this is additive, not a
    behaviour change to anything already shipped.
    """
    token = _namespace.set(namespace)
    try:
        yield
    finally:
        _namespace.reset(token)


def current_namespace() -> str | None:
    return _namespace.get()


def node_id(key: str) -> int:
    """Derive the integer node id for a canonical key.

    Stable across processes and runs -- blake2b is not salted here on
    purpose, beyond the request-scoped namespace prefix from `scan_scope()`.
    """
    ns = _namespace.get()
    full = f"{ns}\x00{key}" if ns is not None else key
    digest = blake2b(full.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") & _MASK


# --- canonical key builders ------------------------------------------------
# One function per node kind so key format lives in exactly one place. Changing
# a format changes every id derived from it, so these are effectively schema.


def symbol_key(pkg: str, version: str, module: str, name: str) -> str:
    """A function/method/class, qualified by the release that contains it."""
    return f"sym:{pkg}@{version}:{module}#{name}"


def module_key(pkg: str, version: str, path: str) -> str:
    return f"mod:{pkg}@{version}:{path}"


def package_key(ecosystem: str, name: str) -> str:
    return f"pkg:{ecosystem}:{name}"


def release_key(ecosystem: str, name: str, version: str) -> str:
    return f"rel:{ecosystem}:{name}@{version}"


def service_key(name: str) -> str:
    return f"svc:{name}"


def advisory_key(advisory_id: str) -> str:
    return f"adv:{advisory_id}"


def identity_key(registry: str, handle: str) -> str:
    return f"who:{registry}:{handle}"


def fact_key(kind: str, subject: str, obj: str, valid_from: int) -> str:
    """A reified temporal fact.

    `valid_from` is part of the identity so that re-observing the same
    subject/object pair over a *different* window creates a distinct fact rather
    than silently overwriting history -- the whole point of keeping time.
    """
    return f"fact:{kind}:{subject}->{obj}@{valid_from}"


class CollisionError(RuntimeError):
    """Two distinct keys derived the same integer id."""


class IdRegistry:
    """Tracks key -> id within a run so collisions surface at ingest.

    At 63 bits and ~10^6 nodes the birthday probability is on the order of
    10^-7, but a silent collision would merge two unrelated symbols and produce
    a *false reachability path* -- the one failure mode that would destroy trust
    in the tool. Cheap to check, so we check.
    """

    def __init__(self) -> None:
        self._seen: dict[int, str] = {}

    def register(self, key: str) -> int:
        nid = node_id(key)
        prior = self._seen.get(nid)
        if prior is not None and prior != key:
            raise CollisionError(f"id {nid} collides: {prior!r} vs {key!r}")
        self._seen[nid] = key
        return nid

    def __len__(self) -> int:
        return len(self._seen)
